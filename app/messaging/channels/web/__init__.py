"""Canal do chat web (ADR-0007)."""

from messaging.channels.base import Channel, DeliveryResult, InboundMessage

# Acima disto não é pergunta: é texto colado por engano, ou tentativa de
# encher o contexto do modelo. O limite protege o custo da chamada de IA.
MAX_QUESTION_CHARS = 2000
MAX_CLIENT_MESSAGE_ID_CHARS = 100


class WebChannel(Channel):
    name = "web"

    def parse_inbound(self, payload: dict) -> InboundMessage:
        conversation_id = payload["conversation_id"]
        client_message_id = str(payload["client_message_id"]).strip()
        text = str(payload["text"]).strip()

        if not client_message_id:
            raise ValueError("client_message_id vazio")
        if len(client_message_id) > MAX_CLIENT_MESSAGE_ID_CHARS:
            raise ValueError("client_message_id longo demais")
        if not text:
            raise ValueError("pergunta vazia")
        if len(text) > MAX_QUESTION_CHARS:
            raise ValueError(f"pergunta acima de {MAX_QUESTION_CHARS} caracteres")

        # O anexo já foi validado e resumido na subida (ADR-0024). O que
        # chega aqui é só a etiqueta dele: tipo, nome, resumo e o token que
        # acha os bytes no depósito.
        anexo = payload.get("anexo") or {}

        return InboundMessage(
            conversation_id=int(conversation_id),
            client_message_id=client_message_id,
            text=text,
            anexo_tipo=str(anexo.get("tipo") or ""),
            anexo_nome=str(anexo.get("nome") or "")[:255],
            anexo_resumo=str(anexo.get("resumo") or ""),
            anexo_token=str(anexo.get("token") or "")[:64],
        )

    def deliver(self, conversation, text: str) -> DeliveryResult:
        # Ver channels/base.py: no chat web a entrega é a própria mensagem
        # gravada pelo serviço, que o navegador busca no polling.
        return DeliveryResult(delivered=True, detail="gravada para o polling")
