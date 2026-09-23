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


def gerar(resposta, user, executor) -> Planilha:
    pergunta = resposta.in_reply_to
    reply = getattr(pergunta, "ai_reply", None) if pergunta is not None else None
    consulta = (
        reply.query_runs.filter(status=QueryRun.Status.SUCCESS).order_by("-attempt").first()
        if reply is not None
        else None
    )
    if consulta is None:
        return Planilha(erro="esta resposta não tem dados para exportar", status=404)

    registro = DataExport(user=user, message=resposta, sql=consulta.sql)
    guard = validate_sql(consulta.sql, get_catalog(), max_rows=EXPORT_MAX_ROWS)
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
            "referencia": consulta.reference_query_id,
            "sql": consulta.sql,
        },
    )

    registro.status = DataExport.Status.OK
    registro.row_count = resultado.row_count
    registro.truncated = resultado.truncated
    registro.duration_ms = resultado.duration_ms
    registro.save()

    nome = slugify(resposta.conversation.title or pergunta.content)[:50] or "consulta"
    return Planilha(conteudo=conteudo, nome=f"jarvis_{nome}_{agora:%Y%m%d-%H%M}.xlsx", linhas=resultado.row_count)
