"""Tarefa Celery que atende um evento do WhatsApp (ADR-0003, ADR-0028).

O webhook só confere o segredo e enfileira: a Evolution espera resposta
rápida, e uma pergunta leva de 10 s a três minutos.

Chats diferentes são atendidos em paralelo; no mesmo chat, um evento de cada
vez, na ordem de chegada (`messaging/fila.py`). O evento que chega antes da
sua vez espera e olha de novo em alguns segundos.
"""

import logging

from celery import shared_task

from messaging import fila
from whatsapp import servicos

logger = logging.getLogger(__name__)


@shared_task(name="whatsapp.receber", acks_late=True, bind=True, max_retries=None)
def receber(self, payload: dict, conversa: str = "", senha: int = 0) -> str:
    if senha and not fila.e_a_vez(conversa, senha):
        raise self.retry(countdown=fila.REVER_EM_S)
    try:
        resultado = servicos.receber(payload, conversa_na_fila=conversa, senha=senha)
    finally:
        if senha:
            fila.passar_a_vez(conversa, senha)
    logger.info("WhatsApp: evento %s", resultado)
    return resultado
