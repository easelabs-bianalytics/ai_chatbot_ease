"""O "Entendi: …" no WhatsApp, enquanto o Jarvis consulta (ADR-0027, ADR-0028).

No chat web a tela mostra o entendimento pelo polling. No WhatsApp não há
tela: quando o planejador diz o que entendeu, sai uma mensagem curta, uma
vez por pergunta. É o jeito mais barato de a pessoa perceber um pedido mal
lido — e escrever "parar" antes da resposta errada.

Ligado ao sinal de `ai_orchestrator.progresso`, para o orquestrador não
conhecer o WhatsApp. Falha aqui nunca derruba a resposta.
"""

import logging

from django.core.cache import cache
from django.dispatch import receiver

from ai_orchestrator import progresso
from whatsapp.cliente import Citacao, cliente_configurado

logger = logging.getLogger(__name__)


def texto_do_aviso(entendimento: str) -> str:
    return f"_Entendi:_ {entendimento}\n\nJá volto com os números."


@receiver(progresso.definido)
def avisar(sender, message_id, estado, **kwargs):
    chave = f"whatsapp:pendente:{message_id}"
    pendente = cache.get(chave)
    if not pendente:
        return
    try:
        cliente = cliente_configurado()
        if estado.get("etapa") == "entendi" and estado.get("entendimento") and not pendente.get("avisado"):
            from whatsapp.servicos import enviar_texto

            citar = Citacao(**pendente["citar"]) if pendente.get("citar") else None
            enviar_texto(cliente, pendente["jid"], texto_do_aviso(estado["entendimento"]), citar=citar)
            cache.set(chave, {**pendente, "avisado": True}, timeout=10 * 60)
        cliente.digitando(pendente["jid"])
    except Exception:  # noqa: BLE001 — aviso é cortesia
        logger.warning("WhatsApp: não consegui mandar o aviso de progresso", exc_info=True)
