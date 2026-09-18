"""Tarefa Celery que responde a uma pergunta (ADR-0003).

Roda fora da requisição HTTP: são até três chamadas de modelo e uma consulta
ao banco de negócio, cada uma com tempo próprio. A API só registra a
pergunta e enfileira.
"""

from celery import shared_task

from ai_orchestrator.orchestrator import handle_message
from ai_orchestrator.provider_factory import get_configured_provider
from datasource.executors.factory import get_configured_executor
from messaging.channels.fake import FakeChannel
from messaging.channels.web import WebChannel
from messaging.models import Message

_CANAIS = {"web": WebChannel, "fake": FakeChannel}


@shared_task(name="ai_orchestrator.process_message")
def process_message(message_id: int, channel_name: str = "web") -> int:
    """Recebe só valores serializáveis: o worker roda em outro processo, e
    objeto do Django não atravessa a fila."""
    message = Message.objects.select_related("conversation").get(pk=message_id)
    reply = handle_message(
        message,
        channel=_CANAIS[channel_name](),
        provider=get_configured_provider(),
        executor=get_configured_executor(),
    )
    return reply.pk
