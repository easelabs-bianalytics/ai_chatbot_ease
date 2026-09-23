"""Canal WhatsApp (ADR-0028).

No contrato `Channel` (ADR-0005), entregar é mandar o texto. No WhatsApp a
resposta tem mais que texto — gráfico em imagem, planilha, continuações —,
e quem monta e envia tudo isso é `whatsapp/servicos.py`, depois que o
orquestrador grava a resposta. Por isso `deliver` aqui não envia: marca a
mensagem para o envio que vem logo depois, e é esse envio que atualiza o
status (entregue ou falhou).
"""

from messaging.channels.base import Channel, DeliveryResult, InboundMessage


class WhatsAppChannel(Channel):
    name = "whatsapp"

    def parse_inbound(self, payload: dict) -> InboundMessage:
        # A leitura do evento da Evolution é `whatsapp/entrada.py`: ele tem
        # grupo, menção, reação e arquivo, que não cabem neste contrato.
        raise NotImplementedError("use whatsapp.entrada.ler")

    def deliver(self, conversation, text: str) -> DeliveryResult:
        return DeliveryResult(delivered=True, detail="whatsapp: a enviar")
