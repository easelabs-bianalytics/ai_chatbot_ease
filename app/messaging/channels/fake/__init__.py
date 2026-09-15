"""Canal de mentira dos testes e do chat pelo terminal.

Aceita os mesmos payloads do canal web, mas guarda em memória o que seria
entregue, para um teste poder afirmar que nada chegou ao usuário.
"""

from messaging.channels.base import DeliveryResult
from messaging.channels.web import WebChannel


class FakeChannel(WebChannel):
    name = "fake"

    def __init__(self):
        self.delivered = []

    def deliver(self, conversation, text: str) -> DeliveryResult:
        self.delivered.append((conversation.pk, text))
        return DeliveryResult(delivered=True, detail="canal fake")
