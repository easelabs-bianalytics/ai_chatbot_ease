"""O "digitando…" no WhatsApp enquanto o Jarvis consulta (ADR-0028).

No chat web a tela mostra o entendimento e as etapas pelo polling. No
WhatsApp a resposta vem direto: até 2026-09-24 saía também uma mensagem
"Entendi: … Já volto com os números", e o Rubens pediu para tirar — no
WhatsApp, uma pessoa responde, não anuncia que vai responder. Fica só o
"digitando…", renovado a cada etapa do orquestrador.

Ligado ao sinal de `ai_orchestrator.progresso`, para o orquestrador não
conhecer o WhatsApp. Falha aqui nunca derruba a resposta.
"""

import logging

from django.core.cache import cache
from django.dispatch import receiver

from ai_orchestrator import progresso
from whatsapp.cliente import cliente_configurado

logger = logging.getLogger(__name__)


@receiver(progresso.definido)
def avisar(sender, message_id, estado, **kwargs):
    pendente = cache.get(f"whatsapp:pendente:{message_id}")
    if not pendente:
        return
    try:
        cliente_configurado().digitando(pendente["jid"])
    except Exception:  # noqa: BLE001 — "digitando" é cortesia
        logger.warning("WhatsApp: não consegui mostrar \"digitando\"", exc_info=True)
