"""Do 👎 ao caso de validação.

Até 2026-09-23 o erro do Jarvis só aparecia quando alguém lia as conversas no
banco à mão. Com a avaliação na tela, cada 👎 — e o "o que estava errado" que
veio com ele — vira aqui um **rascunho de caso**, no formato de
`casos_validacao.yaml`: a pergunta, as perguntas anteriores da conversa, a
referência que a IA usou e uma nota com o que a pessoa disse, a resposta e o
SQL.

Rascunho não entra na suíte sozinho (`rascunho: true`): alguém do time de BI
confere o `esperado`, acrescenta as regras que provam o acerto
(`sql_deve_conter`, `resposta_deve_conter`) e tira a marca. Daí em diante o
erro vira teste, e a suíte mede se ele voltou.
"""

import re
import unicodedata
from pathlib import Path

import yaml
from django.utils import timezone

from ai_orchestrator.models import AIReply
from datasource.models import QueryRun
from messaging.models import Avaliacao, Message
from reporting.cases import DEFAULT_USO_PATH

PERGUNTAS_ANTES = 4
TRECHO_DA_RESPOSTA = 400
TRECHO_DO_SQL = 800

CABECALHO = """\
# Casos que nasceram do uso: cada 👎 na tela vira um rascunho aqui
# (`manage.py casos_do_uso`). Rascunho (`rascunho: true`) não roda na suíte.
#
# Para promover um rascunho: confira `esperado` e `grupo`, acrescente as regras
# que provam o acerto (`sql_deve_conter`, `sql_nao_deve_conter`,
# `resposta_deve_conter`) e apague a linha `rascunho: true`. O formato é o de
# casos_validacao.yaml.
"""

# A decisão que a pessoa marcou como errada diz pouco do que era o certo; o
# ponto de partida é "responder com dado", e o revisor ajusta.
_ESPERADO = {
    AIReply.Decision.CLARIFY: "answer_with_data",
    AIReply.Decision.UNKNOWN: "answer_with_data",
    AIReply.Decision.OUT_OF_SCOPE: "answer_with_data",
}


def _texto(valor, limite=None) -> str:
    texto = " ".join(str(valor or "").split())
    return texto[:limite] if limite else texto


def _slug(texto: str, limite: int = 40) -> str:
    sem_acento = unicodedata.normalize("NFD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", sem_acento).strip("-")[:limite].strip("-") or "pergunta"


def rascunho(avaliacao: Avaliacao) -> dict:
    """O rascunho de caso de uma avaliação 👎."""
    resposta = avaliacao.message
    pergunta = resposta.in_reply_to
    reply = getattr(pergunta, "ai_reply", None) if pergunta is not None else None

    antes = list(
        Message.objects.filter(
            conversation_id=resposta.conversation_id,
            direction=Message.Direction.INBOUND,
            id__lt=pergunta.pk,
        ).order_by("-id").values_list("content", flat=True)[:PERGUNTAS_ANTES]
    )[::-1]

    consulta = (
        reply.query_runs.filter(status=QueryRun.Status.SUCCESS).order_by("-attempt", "-id").first()
        if reply is not None else None
    )
    decisao = reply.decision if reply is not None else ""
    quando = timezone.localtime(avaliacao.updated_at).strftime("%d/%m/%Y")
    nota = [
        f"👎 em {quando} (mensagem {resposta.pk}, conversa {resposta.conversation_id}):"
        f" {_texto(avaliacao.comentario) or 'sem comentário'}.",
        f"Decisão: {decisao or 'sem registro'}{f' ({reply.rule})' if reply is not None and reply.rule else ''}.",
        f"Resposta: {_texto(resposta.content, TRECHO_DA_RESPOSTA)}",
    ]
    if reply is not None and (reply.raw_response or {}).get("entendimento"):
        nota.append(f"Entendido: {_texto(reply.raw_response['entendimento'])}")
    if consulta is not None:
        nota.append(f"SQL: {_texto(consulta.sql, TRECHO_DO_SQL)}")

    caso = {
        "id": f"U{resposta.pk}-{_slug(pergunta.content)}",
        "grupo": "seguimento" if antes else "referencia",
        "rascunho": True,
    }
    if antes:
        caso["antes"] = antes
    caso["pergunta"] = _texto(pergunta.content)
    caso["esperado"] = _ESPERADO.get(decisao, "answer_with_data")
    if consulta is not None and consulta.reference_query_id:
        caso["referencia"] = consulta.reference_query_id
    caso["comparar_resultado"] = False
    caso["nota"] = " ".join(nota)
    return caso


def pendentes(todas: bool = False):
    """Os 👎 ainda não exportados (ou todos), dos mais antigos aos novos."""
    avaliacoes = Avaliacao.objects.filter(
        nota=Avaliacao.Nota.ERRADA, message__in_reply_to__isnull=False
    ).select_related("message__in_reply_to__ai_reply").order_by("id")
    return avaliacoes if todas else avaliacoes.filter(caso_exportado_em__isnull=True)


def acrescentar(casos: list, path=DEFAULT_USO_PATH) -> int:
    """Acrescenta os rascunhos ao arquivo, sem repetir id. Devolve quantos
    entraram."""
    path = Path(path)
    existentes = []
    if path.exists():
        existentes = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("casos") or []
    ids = {c.get("id") for c in existentes}
    novos = [c for c in casos if c["id"] not in ids]
    if not novos:
        return 0
    corpo = yaml.safe_dump(
        {"casos": existentes + novos}, allow_unicode=True, sort_keys=False, width=100
    )
    path.write_text(CABECALHO + "\n" + corpo, encoding="utf-8")
    return len(novos)


def em_yaml(casos: list) -> str:
    return yaml.safe_dump({"casos": casos}, allow_unicode=True, sort_keys=False, width=100)
