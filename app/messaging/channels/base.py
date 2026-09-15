"""Interface abstrata de canal (ADR-0005).

Serviços e orquestrador dependem só deste contrato. Hoje existe um canal
real, o chat web, e um fake para os testes afirmarem que nada foi entregue.

No chat web, entregar é gravar a mensagem de saída: é ela que o navegador
busca no polling. Quem grava é `messaging/services.py`, um lugar só, para a
auditoria não depender de cada canal lembrar de registrar. Ao canal sobra o
que é específico dele — num canal externo (Slack, e-mail) seria a chamada
HTTP. Por isso `WebChannel.deliver` quase não tem trabalho a fazer.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class InboundMessage:
    """Pergunta já normalizada, independente do formato do canal."""

    conversation_id: int
    client_message_id: str
    text: str


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    detail: str = ""


class Channel(ABC):
    name: str

    @abstractmethod
    def parse_inbound(self, payload: dict) -> InboundMessage:
        """Payload cru do canal para InboundMessage.

        Levanta KeyError se faltar campo obrigatório e ValueError se o
        conteúdo for inválido (texto vazio, longo demais).
        """

    @abstractmethod
    def deliver(self, conversation, text: str) -> DeliveryResult:
        """Entrega a resposta ao usuário pelo canal."""
