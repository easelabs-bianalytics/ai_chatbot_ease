"""Tarefa Celery que responde a uma pergunta (ADR-0003).

Roda fora da requisição HTTP: são até três chamadas de modelo e uma consulta
ao banco de negócio, cada uma com tempo próprio. A API só registra a
pergunta e enfileira.

Conversas diferentes são respondidas em paralelo; na mesma conversa, uma
pergunta de cada vez, na ordem em que foram gravadas (`messaging/fila.py`).
"""

from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from ai_orchestrator.orchestrator import handle_message
from ai_orchestrator.provider_factory import get_configured_provider
from datasource.executors.factory import get_configured_executor
from messaging import fila
from messaging.channels.fake import FakeChannel
from messaging.channels.web import WebChannel
from messaging.models import Message

_CANAIS = {"web": WebChannel, "fake": FakeChannel}


def _tem_pergunta_anterior_pendente(message) -> bool:
    """Uma pergunta mais antiga da mesma conversa ainda sendo respondida.

    A mensagem do chat web já está gravada quando a tarefa roda, então a
    ordem de chegada é a do id. Pergunta pendente há mais de
    `fila.ESPERA_MAXIMA_S` é dada como perdida (o worker caiu no meio dela)
    e não segura a fila."""
    return Message.objects.filter(
        conversation_id=message.conversation_id,
        direction=Message.Direction.INBOUND,
        id__lt=message.id,
        status__in=(Message.Status.RECEIVED, Message.Status.PROCESSING),
        created_at__gte=timezone.now() - timedelta(seconds=fila.ESPERA_MAXIMA_S),
    ).exists()


@shared_task(name="ai_orchestrator.process_message", bind=True, max_retries=None)
def process_message(self, message_id: int, channel_name: str = "web") -> int:
    """Recebe só valores serializáveis: o worker roda em outro processo, e
    objeto do Django não atravessa a fila."""
    message = Message.objects.select_related("conversation").get(pk=message_id)
    if _tem_pergunta_anterior_pendente(message):
        raise self.retry(countdown=fila.REVER_EM_S)
    reply = handle_message(
        message,
        channel=_CANAIS[channel_name](),
        provider=get_configured_provider(),
        executor=get_configured_executor(),
    )
    return reply.pk
