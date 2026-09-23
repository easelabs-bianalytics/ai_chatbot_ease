"""Tarefa Celery que atende um evento do WhatsApp (ADR-0003, ADR-0028).

O webhook só confere o segredo e enfileira: a Evolution espera resposta
rápida, e uma pergunta leva de 10 s a três minutos.
"""

import logging

from celery import shared_task

from whatsapp import servicos

logger = logging.getLogger(__name__)


@shared_task(name="whatsapp.receber", acks_late=True)
def receber(payload: dict) -> str:
    resultado = servicos.receber(payload)
    logger.info("WhatsApp: evento %s", resultado)
    return resultado
