"""Validador determinístico do SQL gerado pela IA (ADR-0008, camada 3).

Com SQL livre (ADR-0014), esta é a principal barreira da aplicação: o
prompt pode ser contornado por uma pergunta bem escrita, e o que decide de
verdade é esta função. A validação é feita sobre a árvore sintática inteira,
e não sobre o texto, para não depender de casar strings — é assim que
`WITH x AS (DELETE ...)` é pego.

O SQL executado é o original, não o reescrito a partir da árvore: reemitir
poderia mudar sutilmente um cast ou um FILTER e alterar o resultado sem
ninguém perceber.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from catalog.loader import Catalog

DIALETO = "postgres"

# Nós que representam escrita, DDL ou comando de sessão. `exp.Command` é o
# que o sqlglot usa para o que não sabe analisar (VACUUM, CALL, DO): recusar
# é o certo, porque não dá para afirmar que é leitura.
_NOMES_DE_ESCRITA = (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterTable",
    "TruncateTable", "Command", "Set", "Copy", "Grant", "Revoke", "Analyze",
)
_NOS_DE_ESCRITA = tuple(
    getattr(exp, nome) for nome in _NOMES_DE_ESCRITA if hasattr(exp, nome)
)

_RAIZES_PERMITIDAS = tuple(
    getattr(exp, nome)
    for nome in ("Select", "Union", "Except", "Intersect", "Subquery")
    if hasattr(exp, nome)
)

_SCHEMAS_DO_SISTEMA = {"pg_catalog", "information_schema", "pg_toast"}

ALIAS_DA_CONSULTA = "bi_guard_q"


def _limpar_final(sql: str) -> str:
    """Tira ponto e vírgula e comentários do fim da consulta.

    As referências do time de BI terminam assim ("-- Sem linha = não está em
    nenhum painel"). Isso precisa sumir antes de embrulhar a consulta no
    limite de linhas: dentro do parêntese, um comentário de linha comentaria
    o próprio fecha-parêntese, e a consulta viraria erro de sintaxe.
    """
    texto = sql.strip()
    while texto:
        if texto.endswith(";"):
            texto = texto[:-1].rstrip()
            continue
        if texto.endswith("*/"):
            inicio = texto.rfind("/*")
            if inicio != -1:
                texto = texto[:inicio].rstrip()
                continue
        linhas = texto.splitlines()
        if linhas and linhas[-1].lstrip().startswith("--"):
            texto = "\n".join(linhas[:-1]).rstrip()
            continue
        break
    return texto


def _e_comando(statement) -> bool:
    """Ponto e vírgula solto e comentário no fim viram um nó próprio no
    sqlglot. Eles não são um segundo comando, e recusar por causa deles
    reprovaria consulta correta."""
    if statement is None:
        return False
    semicolon = getattr(exp, "Semicolon", None)
    if semicolon is not None and isinstance(statement, semicolon):
        return False
    return True


@dataclass(frozen=True)
class GuardResult:
    approved: bool
    reason: str = ""
    # Consulta pronta para executar: a original, com o limite de linhas.
    sql: str = ""


def _estrela_so_de_valores(estrela) -> bool:
    """O * que o próprio sqlglot cria ao ler `WITH x(a, b) AS (VALUES ...)`.

    A árvore vira `SELECT * FROM (VALUES ...)`: o asterisco só seleciona os
    literais escritos na consulta, não coluna de tabela nenhuma. Recusá-lo
    barrou, em 2026-09-21, a consulta que preenchia uma planilha — o modelo
    listou os nomes da planilha num VALUES, que é o jeito certo de fazer.

    Estreito de propósito: vale só se a fonte da seleção é UNICAMENTE o
    VALUES, sem join. Qualquer outro * continua recusado.
    """
    selecao = estrela.find_ancestor(exp.Select)
    if selecao is None or selecao.args.get("joins"):
        return False
    origem = selecao.args.get("from") or selecao.args.get("from_")
    fonte = getattr(origem, "this", None)
    if isinstance(fonte, exp.Subquery):
        fonte = fonte.this
    return isinstance(fonte, exp.Values)


def _recusa(motivo: str) -> GuardResult:
    return GuardResult(approved=False, reason=motivo)


def _nome_da_tabela(tabela: exp.Table) -> str:
    schema = (tabela.db or "").lower()
    nome = (tabela.name or "").lower()
    return f"{schema}.{nome}" if schema else nome


def _aplicar_limite(sql: str, max_rows: int) -> str:
    """Embrulha a consulta com uma linha a mais que o limite.

    A linha extra é o que permite saber que o resultado foi cortado: sem
    ela, 500 linhas e "exatamente 500 linhas" seriam indistinguíveis, e a
    resposta poderia afirmar um total que não é o total.
    """
    return (
        f"SELECT * FROM (\n{_limpar_final(sql)}\n) AS {ALIAS_DA_CONSULTA} "
        f"LIMIT {max_rows + 1}"
    )


def validate_sql(sql: str, catalog: Catalog, max_rows: int | None = None) -> GuardResult:
    """Aprova ou recusa uma consulta, com o motivo em português.

    O motivo volta para a IA na correção única (ADR-0014), então ele precisa
    dizer o que fazer diferente, não só que foi recusado.
    """
    texto = (sql or "").strip()
    if not texto:
        return _recusa("consulta vazia")

    try:
        statements = sqlglot.parse(texto, read=DIALETO)
    except sqlglot.ParseError as exc:
        return _recusa(f"não foi possível interpretar o SQL: {exc}")

    statements = [s for s in statements if _e_comando(s)]
    if len(statements) != 1:
        return _recusa(
            f"a consulta tem {len(statements)} comandos; envie um único SELECT"
        )

    arvore = statements[0]
    if not isinstance(arvore, _RAIZES_PERMITIDAS):
        return _recusa(
            f"apenas SELECT é permitido, e isto é {type(arvore).__name__.upper()}"
        )

    for no in arvore.walk():
        if isinstance(no, _NOS_DE_ESCRITA):
            return _recusa(
                f"a consulta contém {type(no).__name__.upper()}; o banco de "
                "negócio é somente leitura"
            )
        if isinstance(no, exp.Lock):
            return _recusa("cláusulas de trava (FOR UPDATE/FOR SHARE) não são permitidas")

    nomes_de_cte = {
        (cte.alias_or_name or "").lower() for cte in arvore.find_all(exp.CTE)
    }

    permitidos = catalog.schemas | catalog.future_schemas
    tabelas = set()
    for tabela in arvore.find_all(exp.Table):
        nome = _nome_da_tabela(tabela)
        if "." not in nome:
            if nome in nomes_de_cte:
                continue
            return _recusa(
                f"a tabela {nome!r} está sem schema; use schema.tabela "
                f"(schemas disponíveis: {', '.join(sorted(permitidos))})"
            )

        schema = nome.split(".", 1)[0]
        if tabela.catalog:
            return _recusa("consulta a outro banco não é permitida")
        if schema in _SCHEMAS_DO_SISTEMA:
            return _recusa(f"o schema {schema!r} é catálogo do sistema e não pode ser consultado")
        if schema not in permitidos:
            return _recusa(
                f"o schema {schema!r} não está liberado; disponíveis: "
                f"{', '.join(sorted(permitidos))}"
            )
        if nome in catalog.blocked_tables:
            return _recusa(f"{nome} não deve ser usada: {catalog.blocked_tables[nome]}")
        tabelas.add(nome)

    bloqueadas = {}
    for tabela in tabelas:
        for coluna in catalog.blocked_columns_for(tabela):
            bloqueadas[coluna] = tabela

    if bloqueadas:
        for coluna in arvore.find_all(exp.Column):
            nome = (coluna.name or "").lower()
            if nome in bloqueadas:
                return _recusa(
                    f"a coluna {nome!r} de {bloqueadas[nome]} é dado pessoal e não "
                    "pode ser consultada, nem para filtrar"
                )
        # COUNT(*) também é um asterisco na árvore, mas não traz coluna
        # nenhuma: só conta linhas. O que expõe dado é o * na seleção.
        estrelas_de_selecao = [
            estrela for estrela in arvore.find_all(exp.Star)
            if not isinstance(estrela.parent, exp.Func) and not _estrela_so_de_valores(estrela)
        ]
        if estrelas_de_selecao:
            return _recusa(
                "SELECT * não é permitido em tabela com coluna de dado pessoal "
                f"({', '.join(sorted(set(bloqueadas.values())))}); liste as colunas"
            )

    for funcao in arvore.find_all(exp.Anonymous):
        nome = str(funcao.this or "").lower()
        if nome in catalog.blocked_functions or nome.startswith(
            catalog.blocked_function_prefixes
        ):
            return _recusa(f"a função {nome}() não é permitida")

    limite = catalog.max_rows if max_rows is None else max_rows
    return GuardResult(approved=True, sql=_aplicar_limite(texto, limite))


def tables_in(sql: str) -> set:
    """Tabelas com schema citadas na consulta, para conferir catálogo contra
    banco (`catalog_check`). Devolve conjunto vazio se não der para
    interpretar o SQL."""
    try:
        arvore = sqlglot.parse_one(sql, read=DIALETO)
    except sqlglot.ParseError:
        return set()

    nomes_de_cte = {(cte.alias_or_name or "").lower() for cte in arvore.find_all(exp.CTE)}
    return {
        _nome_da_tabela(t)
        for t in arvore.find_all(exp.Table)
        if "." in _nome_da_tabela(t) or _nome_da_tabela(t) not in nomes_de_cte
    } - {n for n in nomes_de_cte}
