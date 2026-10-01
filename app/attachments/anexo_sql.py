"""A planilha anexada como tabela da consulta: `anexo.<aba>` (ADR-0031).

O modelo escreve `FROM anexo.painel a LEFT JOIN audit.medico m ON ...` como
escreveria com qualquer tabela do banco. Antes de executar, o executor troca
`anexo.painel` por uma CTE montada com `unnest` sobre os valores das células,
passados como PARÂMETRO da consulta — nunca colados no texto do SQL. Assim:

- a consulta parte das linhas da pessoa, e não do cadastro inteiro (conversa
  44, 2026-09-29: o Jarvis varreu `audit.medico` inteiro, a consulta parou em
  50 mil linhas e só 84 dos 230 CRMs foram preenchidos);
- o conteúdo das células vai ao banco, que é somente leitura, e não ao
  modelo: a ADR-0024 ("só a forma sobe ao modelo") continua valendo, e o
  custo da pergunta não muda com o tamanho da planilha;
- valor de célula não tem como virar SQL: ele é dado do `unnest`, escapado
  pelo driver.

Cada tabela traz `_linha`, o número da linha no arquivo, que é por onde o
resultado volta à linha certa no preenchimento.
"""

import re
from datetime import date, datetime, time

from attachments.planilha import COLUNA_DA_LINHA, SCHEMA_DO_ANEXO, SUFIXO_DAS_CELULAS, Coluna, Pagina
from datasource.executors.base import QueryExecutor

# Tipo do perfil → tipo do array no Postgres.
_TIPOS = {"número": "numeric", "data": "timestamp", "texto": "text", "vazia": "text"}

_REFERENCIA = re.compile(
    rf'\b{SCHEMA_DO_ANEXO}\s*\.\s*(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))', re.IGNORECASE
)


def tabelas(estrutura) -> dict:
    """{nome da tabela (sem schema): Pagina} de uma planilha lida: a tabela
    principal de cada aba e a grade de células dela (`<aba>_celulas`)."""
    if estrutura is None:
        return {}
    disponiveis = {}
    for pagina in estrutura.paginas:
        if not pagina.nome_sql:
            continue
        disponiveis[pagina.nome_sql] = pagina
        if pagina.celulas:
            disponiveis[pagina.nome_sql + SUFIXO_DAS_CELULAS] = _pagina_das_celulas(pagina)
    return disponiveis


def _pagina_das_celulas(pagina):
    """A grade de células como se fosse uma aba: `_linha` (a linha), coluna
    (a letra), valor (como texto), numero (quando é número) e formula. É
    por ela que o modelo lê a premissa em K40 ou a meta total na linha 34."""
    registros = tuple(
        (linha, (letra, valor, valor if isinstance(valor, (int, float)) and not isinstance(valor, bool) else None,
                 formula))
        for linha, letra, valor, formula in pagina.celulas
    )
    colunas = (
        Coluna("coluna", "texto", (), nome_sql="coluna", indice=0),
        Coluna("valor", "texto", (), nome_sql="valor", indice=1),
        Coluna("numero", "número", (), nome_sql="numero", indice=2),
        Coluna("formula", "texto", (), nome_sql="formula", indice=3),
    )
    return Pagina(nome=f"{pagina.nome} (células)", colunas=colunas, linhas=len(registros),
                  nome_sql=pagina.nome_sql + SUFIXO_DAS_CELULAS, registros=registros)


def _fora_de_literal(sql: str) -> list:
    """Máscara: True onde o caractere está fora de '...' e de comentário.
    O nome da tabela dentro de um texto ('anexo.x') não é referência."""
    fora = [True] * len(sql)
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2
                    continue
                if sql[j] == "'":
                    break
                j += 1
            for k in range(i, min(j + 1, n)):
                fora[k] = False
            i = j + 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                fora[k] = False
            i = j
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            for k in range(i, j):
                fora[k] = False
            i = j
            continue
        i += 1
    return fora


def _achados(sql: str):
    fora = _fora_de_literal(sql)
    for achado in _REFERENCIA.finditer(sql):
        if fora[achado.start()]:
            yield achado, (achado.group(1) or achado.group(2)).lower()


def referencias(sql: str) -> set:
    """Nomes das tabelas `anexo.*` citadas na consulta (sem o schema)."""
    return {nome for _, nome in _achados(sql or "")}


def nome_da_cte(nome: str) -> str:
    return f"{SCHEMA_DO_ANEXO}__{nome}"


def _renomear(sql: str) -> str:
    partes, fim = [], 0
    for achado, nome in _achados(sql):
        partes.append(sql[fim:achado.start()])
        partes.append(nome_da_cte(nome))
        fim = achado.end()
    partes.append(sql[fim:])
    return "".join(partes)


def _para_o_banco(valor, tipo: str):
    """O valor da célula no tipo do array. O que não cabe no tipo vira NULL
    — a coluna "número" só tem número, pelo perfil, mas célula de erro do
    Excel (#N/D) existe."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if tipo == "numeric":
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            return None
        return valor
    if tipo == "timestamp":
        if isinstance(valor, datetime):
            return valor.isoformat(sep=" ")
        if isinstance(valor, date):
            return datetime.combine(valor, time()).isoformat(sep=" ")
        return None
    if isinstance(valor, float) and valor.is_integer():
        # 104608.0 é como o Excel guarda o número 104608: em texto, sem ".0".
        return str(int(valor))
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    return str(valor)


def _com_estrela(sql: str) -> bool:
    """A consulta pede todas as colunas de alguma tabela: `a.*`, ou um
    `SELECT *` além do que o validador põe em volta."""
    return bool(re.search(r"\w\.\*", sql)) or len(re.findall(r"select\s+\*", sql, re.IGNORECASE)) > 1


def _colunas_citadas(pagina, sql: str) -> list:
    """Índices das colunas que a consulta cita. Uma planilha de 20 mil linhas
    e 60 colunas mandaria 1,2 milhão de valores ao banco para a consulta usar
    três colunas; vão só as citadas (todas, se houver `*`).

    A coluna interna (o CRM normalizado) só entra citada pelo nome: um
    `SELECT a.*` que vira aba nova não pode levá-la ao arquivo da pessoa."""
    def citada(c):
        return bool(re.search(rf'(?<![A-Za-z0-9_]){re.escape(c.nome_sql)}(?![A-Za-z0-9_])', sql, re.IGNORECASE))

    if sql is None:
        return list(range(len(pagina.colunas)))
    estrela = _com_estrela(sql)
    return [
        i for i, c in enumerate(pagina.colunas)
        if citada(c) or (estrela and not getattr(c, "interna", False))
    ]


def _cte(pagina, sql: str | None = None) -> tuple:
    """(texto da CTE, parâmetros): uma coluna por array, na ordem."""
    indices = _colunas_citadas(pagina, sql)
    tipos = [_TIPOS.get(pagina.colunas[i].tipo, "text") for i in indices]
    colunas = ", ".join([COLUNA_DA_LINHA, *(f'"{pagina.colunas[i].nome_sql}"' for i in indices)])
    arrays = ", ".join(["%s::bigint[]", *(f"%s::{t}[]" for t in tipos)])
    params = [[numero for numero, _ in pagina.registros]]
    for i, tipo in zip(indices, tipos):
        params.append([_para_o_banco(valores[i], tipo) for _, valores in pagina.registros])
    texto = f"{nome_da_cte(pagina.nome_sql)}({colunas}) AS (SELECT * FROM unnest({arrays}))"
    return texto, params


def expandir(sql: str, disponiveis: dict) -> tuple:
    """(sql, params) prontos para o driver, ou (sql, None) sem anexo.

    `sql` é o que o validador aprovou (já embrulhado no limite de linhas).
    As CTEs entram na frente; as CTEs do próprio modelo, lá dentro, enxergam
    as de fora — é assim no Postgres. O `%` do SQL do modelo é dobrado,
    porque com parâmetros o driver o leria como marcador."""
    usadas = sorted(referencias(sql) & set(disponiveis))
    if not usadas:
        return sql, None
    ctes, params = [], []
    for nome in usadas:
        texto, valores = _cte(disponiveis[nome], sql)
        ctes.append(texto)
        params.extend(valores)
    corpo = _renomear(sql).replace("%", "%%")
    return "WITH " + ",\n".join(ctes) + "\n" + corpo, params


class ExecutorComAnexo(QueryExecutor):
    """Embrulha o executor da conversa: a consulta que cita `anexo.*` sai
    com as CTEs e os parâmetros; a que não cita passa como veio.

    `registro` é um dict da auditoria: as tabelas usadas ficam anotadas nele
    (`anexo_sql`), e é por elas que se sabe depois que a resposta usou a
    planilha — a planilha continua na conversa enquanto é usada."""

    def __init__(self, interno: QueryExecutor, disponiveis: dict, registro: dict | None = None):
        self._interno = interno
        self._disponiveis = disponiveis
        self._registro = registro

    @property
    def interno(self) -> QueryExecutor:
        return self._interno

    def run(self, sql: str, max_rows: int | None = None, params=None):
        expandido, parametros = expandir(sql, self._disponiveis)
        if parametros is None:
            return self._interno.run(sql, max_rows=max_rows)
        if self._registro is not None:
            usadas = set(self._registro.get("anexo_sql") or ()) | (referencias(sql) & set(self._disponiveis))
            self._registro["anexo_sql"] = sorted(usadas)
        return self._interno.run(expandido, max_rows=max_rows, params=parametros)
