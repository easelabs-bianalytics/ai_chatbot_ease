"""Reconhecimentos que deram certo viram rascunho de consulta de referência (ADR-0033).

Uma pergunta sem referência passa pelo reconhecimento: o Jarvis olha o dado,
escreve a consulta final e diz as premissas. Quando ela foi respondida e
ninguém deu 👎, a consulta é uma candidata a referência — a próxima pergunta
parecida sai direto, sem o reconhecimento (uma chamada a menos) e com o
critério já combinado. Quem decide se entra no documento é o time de BI: aqui
só se monta o rascunho, no formato das referências.
"""

from ai_orchestrator.models import AIReply
from datasource.models import QueryRun
from messaging.models import Avaliacao


def pendentes(desde=None):
    """Respostas que passaram pelo reconhecimento, foram respondidas e não
    levaram 👎 — das mais antigas às mais novas."""
    respostas = AIReply.objects.filter(
        decision=AIReply.Decision.ANSWERED, raw_response__has_key="reconhecimento"
    ).select_related("message").order_by("id")
    if desde is not None:
        respostas = respostas.filter(created_at__gte=desde)
    com_polegar_para_baixo = set(
        Avaliacao.objects.filter(nota=Avaliacao.Nota.ERRADA)
        .values_list("message__in_reply_to_id", flat=True)
    )
    return [r for r in respostas if r.message_id not in com_polegar_para_baixo]


def _consulta_final(resposta):
    """A última consulta que deu certo: as de reconhecimento rodam antes."""
    return (
        resposta.query_runs.filter(status=QueryRun.Status.SUCCESS)
        .order_by("-attempt", "-id")
        .values_list("sql", flat=True)
        .first()
    )


def rascunho(resposta) -> str:
    """Um bloco no formato do documento de referência, para revisão."""
    pergunta = " ".join((resposta.message.content or "").split())
    sql = (_consulta_final(resposta) or "").strip().rstrip(";")
    premissas = (resposta.raw_response or {}).get("premissas") or ""
    conferido = [c.get("o_que_confere") for c in (resposta.raw_response or {}).get("reconhecimento") or []]
    linhas = [
        f'*"{pergunta}"*',
        "",
        "```sql",
        f"-- RASCUNHO · {pergunta[:90]}",
        sql + ";",
    ]
    if premissas:
        linhas += [f"-- Premissas: {linha}" for linha in premissas.splitlines() if linha.strip()]
    if conferido:
        linhas.append("-- Reconhecimento conferiu: " + "; ".join(filter(None, conferido)))
    linhas.append(f"-- Origem: resposta #{resposta.pk}, {resposta.created_at:%d/%m/%Y}. Revisar o id e o texto.")
    linhas.append("```")
    return "\n".join(linhas)
