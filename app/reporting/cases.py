"""Casos de validação da IA, ligados ao documento de referência (Fase 7).

Os casos moram em `app/knowledge/casos_validacao.yaml` e não carregam SQL
próprio: cada um aponta para uma consulta do
`chatbot_bi_referencia_querys.md` e diz o que muda nela (parâmetros e
trocas de texto) para virar o gabarito daquela pergunta. Assim o gabarito
acompanha o documento — e, se o time de BI reescrever uma consulta, a troca
deixa de casar e a suíte avisa em vez de comparar com um gabarito velho.

Os mesmos casos carregam as regras de negócio do documento que o SQL da IA
precisa respeitar (filtros padrão do CDD, venda PBM confirmada, dia 0 da
ruptura...), porque um resultado parecido com o gabarito não prova que a
consulta está certa num período em que as duas coincidem por acaso.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp

from catalog.errors import CatalogError
from catalog.loader import BASE_DIR
from datasource.sql_guard import DIALETO

DEFAULT_CASES_PATH = BASE_DIR / "app" / "knowledge" / "casos_validacao.yaml"
# Casos que nasceram do uso: cada 👎 com comentário vira um rascunho aqui
# (`casos_do_uso`). Rascunho não roda na suíte até alguém revisar o esperado e
# tirar `rascunho: true`; daí em diante é caso como qualquer outro.
DEFAULT_USO_PATH = BASE_DIR / "app" / "knowledge" / "casos_do_uso.yaml"

ESPERADOS = frozenset(
    {"answer_with_data", "clarify", "unknown", "out_of_scope", "indisponivel"}
)
GRUPOS = frozenset(
    {
        "referencia",
        "cruzado",
        "esclarecimento",
        "fora_de_escopo",
        "indisponivel",
        "seguranca",
        "seguimento",
    }
)

# `:nome` é parâmetro; `::tipo` é cast e fica como está.
_PARAMETRO = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
# Prefixo de alias ou de schema (`fc.`, `cddd.`): some na normalização para
# que a regra não dependa do alias que a IA escolheu. Começa por letra para
# não comer o `0.` de `0.89`.
_PREFIXO = re.compile(r"\b[a-z_][a-z0-9_]*\.")


def normalizar_sql(sql: str) -> str:
    """SQL em forma comparável: sem comentários, sem espaços, minúsculo e
    sem prefixo de alias ou schema."""
    sem_comentario = re.sub(r"--[^\n]*", "", sql or "").lower()
    # O prefixo sai antes de juntar tudo: sem os espaços, `AND p.data` vira
    # `andp.data` e o `and` iria embora junto com o alias.
    sem_prefixo = _PREFIXO.sub("", sem_comentario)
    return re.sub(r"\s+", "", sem_prefixo)


def _como_lista_de_alternativas(itens) -> tuple:
    """Cada regra é um texto ou uma lista de alternativas (basta uma)."""
    regras = []
    for item in itens or []:
        alternativas = item if isinstance(item, list) else [item]
        regras.append(tuple(normalizar_sql(str(a)) for a in alternativas))
    return tuple(regras)


@dataclass(frozen=True)
class Troca:
    de: str
    para: str


@dataclass(frozen=True)
class ValidationCase:
    id: str
    grupo: str
    pergunta: str
    esperado: tuple
    referencia: str = ""
    antes: tuple = ()
    parametros: dict = field(default_factory=dict)
    trocas: tuple = ()
    sql_deve_conter: tuple = ()
    sql_nao_deve_conter: tuple = ()
    resposta_deve_conter: tuple = ()
    comparar_resultado: bool = True
    # Colunas do gabarito que respondem a pergunta. Vazio = todas. A
    # referência às vezes abre detalhes que a pergunta não pediu (a B01 abre
    # os componentes do Sell Out); exigir todos reprovaria a IA por trazer
    # menos coluna do que o exemplo, não por errar número.
    colunas_do_gabarito: tuple = ()
    nota: str = ""
    rascunho: bool = False

    @property
    def tem_gabarito(self) -> bool:
        return "answer_with_data" in self.esperado and bool(self.referencia) and self.comparar_resultado


@dataclass(frozen=True)
class RegraDeNegocio:
    nome: str
    referencias: frozenset
    sql_deve_conter: tuple = ()
    sql_nao_deve_conter: tuple = ()


@dataclass(frozen=True)
class CaseSuite:
    hoje: str
    regras: tuple
    casos: tuple

    def regras_para(self, caso: ValidationCase) -> tuple:
        return tuple(r for r in self.regras if caso.referencia in r.referencias)


def _literal(valor) -> str:
    if isinstance(valor, bool):
        raise CatalogError("parâmetro booleano não é suportado nos casos")
    if isinstance(valor, (int, float)):
        return str(valor)
    return "'" + str(valor).replace("'", "''") + "'"


def aplicar_trocas(sql: str, trocas, contexto: str) -> str:
    for troca in trocas:
        if troca.de not in sql:
            raise CatalogError(
                f"{contexto}: o trecho {troca.de!r} não existe mais na consulta de "
                "referência — o documento mudou e o caso precisa ser revisto"
            )
        sql = sql.replace(troca.de, troca.para)
    return sql


def ligar_parametros(sql: str, parametros: dict, contexto: str) -> str:
    def substituir(m):
        nome = m.group(1)
        if nome not in parametros:
            raise CatalogError(f"{contexto}: falta o parâmetro :{nome}")
        return _literal(parametros[nome])

    # Comentário não é consulta: um `:nome` citado ali não pede valor.
    linhas = []
    for linha in sql.splitlines():
        codigo, sep, comentario = linha.partition("--")
        linhas.append(_PARAMETRO.sub(substituir, codigo) + sep + comentario)
    return "\n".join(linhas)


def sql_gabarito(caso: ValidationCase, catalog) -> str:
    """A consulta de referência ajustada para a pergunta do caso."""
    referencias = {r.id: r for r in catalog.references}
    if caso.referencia not in referencias:
        raise CatalogError(f"{caso.id}: referência {caso.referencia} não existe no documento")
    sql = aplicar_trocas(referencias[caso.referencia].sql, caso.trocas, caso.id)
    sql = ligar_parametros(sql, caso.parametros, caso.id)

    arvore = sqlglot.parse_one(sql, read=DIALETO)
    if any(True for _ in arvore.find_all(exp.Placeholder)):
        raise CatalogError(f"{caso.id}: o gabarito ainda tem parâmetro sem valor")
    return sql


def conferir_regras(sql: str, caso: ValidationCase, suite: CaseSuite) -> list:
    """Regras do documento que o SQL não cumpriu, em português."""
    normalizado = normalizar_sql(sql)
    falhas = []
    grupos = [(f"caso {caso.id}", caso.sql_deve_conter, caso.sql_nao_deve_conter)]
    grupos += [(r.nome, r.sql_deve_conter, r.sql_nao_deve_conter) for r in suite.regras_para(caso)]
    for origem, deve, nao_deve in grupos:
        for alternativas in deve:
            if not any(a in normalizado for a in alternativas):
                falhas.append(f"{origem}: faltou {' ou '.join(alternativas)}")
        for alternativas in nao_deve:
            for a in alternativas:
                if a in normalizado:
                    falhas.append(f"{origem}: não devia conter {a}")
    return falhas


def _caso(bruto: dict) -> ValidationCase:
    faltando = [c for c in ("id", "grupo", "pergunta", "esperado") if c not in bruto]
    if faltando:
        raise CatalogError(f"caso sem {', '.join(faltando)}: {bruto!r}")
    identificador = str(bruto["id"])

    esperado = bruto["esperado"]
    esperado = tuple(esperado if isinstance(esperado, list) else [esperado])
    invalidos = set(esperado) - ESPERADOS
    if invalidos:
        raise CatalogError(f"{identificador}: esperado inválido {sorted(invalidos)}")
    if bruto["grupo"] not in GRUPOS:
        raise CatalogError(f"{identificador}: grupo inválido {bruto['grupo']!r}")

    return ValidationCase(
        id=identificador,
        grupo=bruto["grupo"],
        pergunta=" ".join(str(bruto["pergunta"]).split()),
        esperado=esperado,
        referencia=str(bruto.get("referencia") or ""),
        antes=tuple(str(p) for p in bruto.get("antes") or []),
        parametros=dict(bruto.get("parametros") or {}),
        trocas=tuple(Troca(de=str(t["de"]), para=str(t["para"])) for t in bruto.get("trocas") or []),
        sql_deve_conter=_como_lista_de_alternativas(bruto.get("sql_deve_conter")),
        sql_nao_deve_conter=_como_lista_de_alternativas(bruto.get("sql_nao_deve_conter")),
        resposta_deve_conter=tuple(str(t) for t in bruto.get("resposta_deve_conter") or []),
        comparar_resultado=bool(bruto.get("comparar_resultado", True)),
        colunas_do_gabarito=tuple(str(c) for c in bruto.get("colunas_do_gabarito") or ()),
        nota=" ".join(str(bruto.get("nota") or "").split()),
        rascunho=bool(bruto.get("rascunho", False)),
    )


def load_casos_do_uso(path: Path = DEFAULT_USO_PATH) -> tuple:
    """Os casos que vieram das avaliações. Arquivo ausente é lista vazia."""
    path = Path(path)
    if not path.exists():
        return ()
    try:
        dados = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CatalogError(f"casos do uso inválidos: {exc}") from exc
    return tuple(_caso(c) for c in dados.get("casos") or [])


def load_cases(path: Path = DEFAULT_CASES_PATH, uso: Path | None = DEFAULT_USO_PATH) -> CaseSuite:
    try:
        dados = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CatalogError(f"casos de validação inválidos: {exc}") from exc

    regras = tuple(
        RegraDeNegocio(
            nome=str(r["nome"]),
            referencias=frozenset(str(i) for i in r["referencias"]),
            sql_deve_conter=_como_lista_de_alternativas(r.get("sql_deve_conter")),
            sql_nao_deve_conter=_como_lista_de_alternativas(r.get("sql_nao_deve_conter")),
        )
        for r in dados.get("regras") or []
    )
    casos = tuple(_caso(c) for c in dados.get("casos") or [])
    if uso is not None:
        casos += load_casos_do_uso(uso)

    ids = [c.id for c in casos]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise CatalogError(f"casos com id repetido: {repetidos}")

    return CaseSuite(hoje=str(dados["hoje"]), regras=regras, casos=casos)
