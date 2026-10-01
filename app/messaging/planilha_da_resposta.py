"""Planilha Excel com o resultado de uma resposta (ADR-0020).

Roda de novo a consulta que a resposta usou — aprovada pelo validador de
novo, com o limite da planilha — e monta o `.xlsx`. Não passa pela IA. Cada
geração fica registrada em `DataExport`. Serve ao botão "Baixar Excel" do
chat web e ao arquivo mandado no WhatsApp (ADR-0028).
"""

from dataclasses import dataclass

from django.utils import timezone
from django.utils.text import slugify

from attachments import anexo_sql, deposito
from attachments.limites import AnexoRecusado
from attachments.planilha import ler_estrutura
from catalog.loader import get_catalog
from datasource.executors.base import QueryExecutionError
from datasource.export import montar_planilha
from datasource.models import DataExport, QueryRun
from datasource.sql_guard import validate_sql

# Bem acima das 500 linhas da conversa, porque o arquivo não passa pela IA
# (não custa token), mas finito, para uma lista gigante não pesar no banco de
# negócio. O tempo máximo da consulta continua valendo.
EXPORT_MAX_ROWS = 50_000


def aviso_de_corte() -> str:
    """O aviso de lista cortada, igual no arquivo, na tela e no WhatsApp.

    Pedido do Rubens (2026-09-30): a pessoa TEM de saber que não veio tudo.
    Até aqui o aviso morava só na aba "Informações" do arquivo, que quase
    ninguém abre, e no WhatsApp sumia quando a tabela tinha título."""
    limite = f"{EXPORT_MAX_ROWS:,}".replace(",", ".")
    return (
        f"A consulta passou de {limite} linhas e a planilha traz só as primeiras {limite}. "
        "Filtre por período, rede, UF ou representante para ter o restante."
    )


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


def _tabelas_da_planilha(reply):
    """As tabelas `anexo.*` da planilha que a resposta usou, ou None se ela
    já saiu do depósito."""
    anexo = (reply.raw_response or {}).get("anexo") or {}
    dados = deposito.buscar(anexo.get("token", ""))
    if dados is None:
        return None
    try:
        return anexo_sql.tabelas(ler_estrutura(anexo.get("nome") or "planilha.xlsx", dados))
    except AnexoRecusado:
        return None


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
    tabelas = {}
    if anexo_sql.referencias(sql):
        # A consulta leu a planilha da conversa (ADR-0031): sem ela, não dá
        # para refazer. Ela fica duas horas depois do último uso.
        tabelas = _tabelas_da_planilha(reply)
        if tabelas is None:
            registro.status, registro.error = DataExport.Status.ERROR, "planilha da conversa expirou"
            registro.save()
            return Planilha(
                erro="a planilha desta conversa expirou; envie o arquivo de novo para gerar o Excel", status=410
            )
        executor = anexo_sql.ExecutorComAnexo(executor, tabelas)
    guard = validate_sql(sql, get_catalog(), max_rows=EXPORT_MAX_ROWS, **({"anexo": tabelas} if tabelas else {}))
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
    observacao = aviso_de_corte() if resultado.truncated else "Lista completa."
    conteudo = montar_planilha(
        resultado.columns,
        resultado.rows,
        {
            "pergunta": pergunta.content,
            "gerada_em": agora.strftime("%d/%m/%Y %H:%M"),
            "linhas": resultado.row_count,
            "observacao": observacao,
            "cortada": bool(resultado.truncated),
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
