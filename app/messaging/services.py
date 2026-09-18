"""Ingestão e entrega de mensagens — independentes do canal (FR-02, FR-13)."""

import logging

from django.db import IntegrityError, transaction

from messaging.channels.base import Channel, InboundMessage
from messaging.models import Message, new_outbound_id

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 60


def _ensure_title(conversation, text: str) -> None:
    """Primeira pergunta vira o título, para a lista de conversas ser
    reconhecível sem abrir uma por uma."""
    if conversation.title:
        return
    conversation.title = text[:TITLE_MAX_CHARS]
    conversation.save(update_fields=["title", "updated_at"])


def ingest_inbound_message(conversation, inbound: InboundMessage) -> tuple[Message, bool]:
    """Persiste a pergunta de forma idempotente.

    created=False significa que já existia mensagem com o mesmo
    client_message_id nesta conversa: clique duplo ou reenvio por falha de
    rede não pode virar duas perguntas, duas chamadas de IA e duas respostas.
    """
    existing = Message.objects.filter(
        conversation=conversation, client_message_id=inbound.client_message_id
    ).first()
    if existing is not None:
        return existing, False

    try:
        with transaction.atomic():
            message = Message.objects.create(
                conversation=conversation,
                direction=Message.Direction.INBOUND,
                content=inbound.text,
                client_message_id=inbound.client_message_id,
                status=Message.Status.RECEIVED,
            )
    except IntegrityError:
        # Corrida entre duas requisições com o mesmo identificador: a
        # constraint única do banco é a garantia final.
        return (
            Message.objects.get(
                conversation=conversation, client_message_id=inbound.client_message_id
            ),
            False,
        )

    _ensure_title(conversation, inbound.text)
    return message, True


def deliver_reply(channel: Channel, conversation, text: str, in_reply_to=None) -> Message:
    """Entrega a resposta pelo canal e grava a mensagem de saída.

    Falha na entrega vira Message.Status.FAILED em vez de exceção: é fronteira
    com serviço externo, e deixar a exceção subir impediria o registro da
    resposta e da auditoria (mesma escolha do projeto de referência).
    """
    status = Message.Status.SENT
    detail = ""

    try:
        result = channel.deliver(conversation, text)
        if not result.delivered:
            status = Message.Status.FAILED
        detail = result.detail
    except Exception as exc:
        logger.warning("Falha ao entregar a resposta pelo canal", exc_info=True)
        status = Message.Status.FAILED
        detail = str(exc)

    return Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        content=text,
        client_message_id=new_outbound_id(),
        status=status,
        delivery_detail=detail,
        in_reply_to=in_reply_to,
    )
