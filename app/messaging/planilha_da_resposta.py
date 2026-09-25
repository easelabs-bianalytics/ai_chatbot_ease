"""Planilha Excel com o resultado de uma resposta (ADR-0020).

Roda de novo a consulta que a resposta usou — aprovada pelo validador de
novo, com o limite da planilha — e monta o `.xlsx`. Não passa pela IA. Cada
geração fica registrada em `DataExport`. Serve ao botão "Baixar Excel" do
chat web e ao arquivo mandado no WhatsApp (ADR-0028).
"""

from dataclasses import dataclass

from django.utils import timezone
from django.utils.text import slugify

from catalog.loader import get_catalog
from datasource.executors.base import QueryExecutionError
from datasource.export import montar_planilha
from datasource.models import DataExport, QueryRun
from datasource.sql_guard import validate_sql

# Bem acima das 500 linhas da conversa, porque o arquivo não passa pela IA
# (não custa token), mas finito, para uma lista gigante não pesar no banco de
# negócio. O tempo máximo da consulta continua valendo.
EXPORT_MAX_ROWS = 50_000


@dataclass(frozen=True)
class Planilha:
    conteudo: bytes = b""
    nome: str = ""
    linhas: int = 0
    erro: str = ""
    status: int = 200
    # Passou até das 50.000 linhas: o arquivo avisa dentro, e quem o manda
    # (WhatsApp) avisa na legenda.
    cortada: bool = False


def consulta_principal(reply):
    """A consulta que responde a pergunta: a última bem-sucedida que NÃO é a
    do preenchimento da planilha anexada.

    O preenchimento roda depois, com outra forma, e era ele que o gráfico e a
    planilha liam — o gráfico saía com as 5 linhas da amostra dele
    (2026-09-25)."""
    if reply is None:
        return None
    sucesso = list(reply.query_runs.filter(status=QueryRun.Status.SUCCESS).order_by("-attempt"))
    for consulta in sucesso:
        if "preenchimento" not in (consulta.result_sample or {}):
            return consulta
    return sucesso[0] if sucesso else None


def _consulta_da_tabela(reply, indice):
    """(sql, referência) da tabela `indice` de uma resposta em blocos.

    Cada tabela guarda a sua consulta desde 2026-09-25. Resposta antiga, sem
    ela: só a de uma consulta dá para refazer com segurança."""
    raw = reply.raw_response or {}
    dados = (raw.get("dados_blocos") or {}).get(str(indice)) or {}
    if dados.get("sql"):
        return dados["sql"], raw.get("reference_query_id", "")
    if len(raw.get("dados_blocos") or {}) <= 1 and not raw.get("entregas") and not raw.get("investigacao"):
        principal = consulta_principal(reply)
        if principal is not None:
            return principal.sql, principal.reference_query_id
    return None, None


def gerar(resposta, user, executor, consulta=None) -> Planilha:
    """`consulta`: o índice da tabela da resposta em blocos. Sem ele, a
    consulta principal da resposta."""
    pergunta = resposta.in_reply_to
    reply = getattr(pergunta, "ai_reply", None) if pergunta is not None else None
    if reply is None:
        return Planilha(erro="esta resposta não tem dados para exportar", status=404)
    if consulta is not None:
        sql, referencia = _consulta_da_tabela(reply, consulta)
    else:
        principal = consulta_principal(reply)
        sql, referencia = (principal.sql, principal.reference_query_id) if principal else (None, None)
    if not sql:
        return Planilha(erro="esta resposta não tem dados para exportar", status=404)

    registro = DataExport(user=user, message=resposta, sql=sql)
    guard = validate_sql(sql, get_catalog(), max_rows=EXPORT_MAX_ROWS)
    if not guard.approved:
        registro.status, registro.error = DataExport.Status.ERROR, guard.reason
        registro.save()
        return Planilha(erro="a consulta não passou no validador", status=400)

    try:
        resultado = executor.run(guard.sql, max_rows=EXPORT_MAX_ROWS)
    except QueryExecutionError as exc:
        registro.status, registro.error = DataExport.Status.ERROR, str(exc)
        registro.save()
        return Planilha(erro="não consegui gerar a planilha agora; tente de novo em instantes", status=502)

    agora = timezone.localtime()
    observacao = (
        f"Lista cortada em {EXPORT_MAX_ROWS:,} linhas; refine o filtro para ter o restante.".replace(",", ".")
        if resultado.truncated
        else "Lista completa."
    )
    conteudo = montar_planilha(
        resultado.columns,
        resultado.rows,
        {
            "pergunta": pergunta.content,
            "gerada_em": agora.strftime("%d/%m/%Y %H:%M"),
            "linhas": resultado.row_count,
            "observacao": observacao,
            "referencia": referencia,
            "sql": sql,
        },
    )

    registro.status = DataExport.Status.OK
    registro.row_count = resultado.row_count
    registro.truncated = resultado.truncated
    registro.duration_ms = resultado.duration_ms
    registro.save()

    nome = slugify(resposta.conversation.title or pergunta.content)[:50] or "consulta"
    return Planilha(conteudo=conteudo, nome=f"jarvis_{nome}_{agora:%Y%m%d-%H%M}.xlsx", linhas=resultado.row_count,
                    cortada=bool(resultado.truncated))
