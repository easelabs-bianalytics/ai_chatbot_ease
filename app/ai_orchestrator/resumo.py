"""O que sustentou uma resposta anterior, em campos, para o planejador ler.

Até 2026-09-23 cada resposta anterior ia ao planejador como os primeiros
1.200 caracteres do SQL. A consulta de uma comparação de vendas (B17) tem uns
2.600: no seguimento da conversa 15 o planejador viu metade dela — sem o
período do mês anterior nem as fontes — e "considere Extras, MP e SS também"
virou a mesma consulta de antes.

Aqui a resposta vira um resumo com o que um seguimento precisa saber: o que
foi entendido, de onde veio (tabelas, referência), com que recorte (filtros,
datas), o que voltou (colunas e as primeiras linhas, com os números) e como
foi desenhado. A última resposta com dado leva também o SQL inteiro, porque é
dela que o seguimento quase sempre parte.
"""

import json
import re

import sqlglot
from sqlglot import exp

from datasource.models import QueryRun
from datasource.sql_guard import DIALETO

# O SQL inteiro vai só na última resposta com dado; acima disto é uma
# consulta que o seguimento não vai reaproveitar linha a linha.
MAX_SQL_DA_ULTIMA = 6000
MAX_FILTROS = 900
LINHAS_DO_RESULTADO = 5
MAX_CONSULTAS = 4

# '2026-01-01', '2026-09', 202609 (cod_anomes): os jeitos de o período
# aparecer nas consultas do documento.
_DATA = re.compile(r"'(\d{4}-\d{2}(?:-\d{2})?)'|\b(20\d{2}(?:0[1-9]|1[0-2]))\b")


def _linha(texto) -> str:
    return " ".join(str(texto or "").split())


def _tabelas_e_filtros(sql: str) -> tuple[list, list]:
    try:
        arvore = sqlglot.parse_one(sql, read=DIALETO)
    except Exception:  # noqa: BLE001 — SQL que não parseia só não ganha resumo
        return [], []
    ctes = {c.alias_or_name for c in arvore.find_all(exp.CTE)}
    tabelas = []
    for tabela in arvore.find_all(exp.Table):
        nome = ".".join(p for p in (tabela.db, tabela.name) if p)
        if nome and tabela.name not in ctes and nome not in tabelas:
            tabelas.append(nome)
    filtros = []
    for clausula in (*arvore.find_all(exp.Where), *arvore.find_all(exp.Having)):
        texto = _linha(clausula.this.sql(dialect=DIALETO))
        if texto and texto not in filtros:
            filtros.append(texto)
    return tabelas, filtros


def _datas(sql: str) -> str:
    achadas = sorted({a or b for a, b in _DATA.findall(sql or "")})
    if not achadas:
        return ""
    return achadas[0] if len(achadas) == 1 else f"de {achadas[0]} a {achadas[-1]} ({len(achadas)} datas citadas)"


def _consulta(run, titulo: str, limite_sql: int) -> list:
    amostra = run.result_sample or {}
    colunas = amostra.get("columns") or []
    linhas = amostra.get("rows") or []
    base = f" (base {run.reference_query_id})" if run.reference_query_id else ""
    partes = [f"- consulta{base}{f' — {titulo}' if titulo else ''}: {run.row_count or 0} linhas"]
    if colunas:
        partes.append(f"  colunas: {', '.join(colunas)}")
    tabelas, filtros = _tabelas_e_filtros(run.sql or "")
    if tabelas:
        partes.append(f"  tabelas: {', '.join(tabelas)}")
    if filtros:
        partes.append(f"  filtros: {' | '.join(filtros)[:MAX_FILTROS]}")
    datas = _datas(run.sql)
    if datas:
        partes.append(f"  datas no SQL: {datas}")
    if linhas:
        primeiras = [dict(zip(colunas, linha)) for linha in linhas[:LINHAS_DO_RESULTADO]]
        partes.append(
            f"  primeiras linhas: {json.dumps(primeiras, ensure_ascii=False, default=str)}"
        )
    if limite_sql:
        partes.append(f"  sql: {_linha(run.sql)[:limite_sql]}")
    return partes


def _grafico(raw: dict) -> str:
    graficos = [b.get("grafico") or {} for b in raw.get("blocos") or () if b.get("tipo") == "grafico"]
    if raw.get("grafico"):
        graficos.append(raw["grafico"])
    descricoes = []
    for g in graficos:
        if g.get("tipo") == "vega":
            marca = (g.get("vega") or {}).get("mark")
            marca = marca.get("type") if isinstance(marca, dict) else marca
            descricoes.append(f"Vega-Lite ({marca or 'composto'})")
            continue
        texto = f"{g.get('tipo')} com x={g.get('x')}, séries={g.get('series')}"
        if g.get("grupo"):
            texto += f", grupo={g['grupo']}"
        for chave in ("empilhado", "separar"):
            if g.get(chave):
                texto += f", {chave}"
        descricoes.append(texto)
    return "; ".join(descricoes)


def resumir(reply, com_sql: bool = False) -> str:
    """O resumo de uma resposta (AIReply), em linhas curtas. Vazio sem nada
    a dizer — conversa e esclarecimento não têm o que resumir."""
    raw = reply.raw_response or {}
    partes = []
    if raw.get("entendimento"):
        partes.append(f"- entendido: {_linha(raw['entendimento'])}")
    if raw.get("pedido_nao_atendido"):
        partes.append(f"- não atendido: {_linha(raw['pedido_nao_atendido'])}")

    execucoes = list(
        reply.query_runs.filter(status=QueryRun.Status.SUCCESS).order_by("-attempt", "-id")
    )
    # Resposta com várias consultas (entregas ou investigação): todas contam,
    # cada uma com o título que a identifica. Na comum, só a que valeu.
    varias = bool(raw.get("entregas") or raw.get("investigacao"))
    escolhidas = list(reversed(execucoes[:MAX_CONSULTAS])) if varias else execucoes[:1]
    limite = MAX_SQL_DA_ULTIMA // max(len(escolhidas), 1) if com_sql else 0
    for run in escolhidas:
        titulo = _linha((run.result_sample or {}).get("hipotese"))
        partes.extend(_consulta(run, titulo, limite))

    grafico = _grafico(raw)
    if grafico:
        partes.append(f"- gráfico: {grafico}")
    return "\n".join(partes)
