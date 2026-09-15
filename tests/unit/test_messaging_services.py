"""Ingestão idempotente e entrega de resposta (messaging/services.py)."""

import pytest

from conversations.models import Conversation
from messaging.channels.base import DeliveryResult, InboundMessage
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from messaging.services import deliver_reply, ingest_inbound_message

pytestmark = pytest.mark.django_db


@pytest.fixture
def conversa(django_user_model):
    user = django_user_model.objects.create_user("ana", password="x")
    return Conversation.objects.create(user=user)


def _inbound(conversa, texto="unidades de Extrato em 2026", client_id="c-1"):
    return InboundMessage(
        conversation_id=conversa.pk, client_message_id=client_id, text=texto
    )


def test_pergunta_reenviada_nao_vira_segunda_mensagem(conversa):
    """Clique duplo ou reenvio por falha de rede geraria duas chamadas de IA e
    duas respostas para a mesma pergunta (FR-02)."""
    primeira, criada = ingest_inbound_message(conversa, _inbound(conversa))
    segunda, criada_de_novo = ingest_inbound_message(conversa, _inbound(conversa))

    assert criada is True
    assert criada_de_novo is False
    assert segunda.pk == primeira.pk
    assert Message.objects.count() == 1


def test_mesmo_identificador_em_outra_conversa_e_pergunta_nova(conversa, django_user_model):
    """A unicidade é por conversa: um cliente com bug repetindo identificador
    não pode fazer um usuário receber a resposta destinada a outro."""
    outro = django_user_model.objects.create_user("bruno", password="x")
    conversa_do_outro = Conversation.objects.create(user=outro)

    ingest_inbound_message(conversa, _inbound(conversa))
    mensagem, criada = ingest_inbound_message(
        conversa_do_outro, _inbound(conversa_do_outro, texto="outra pergunta")
    )

    assert criada is True
    assert mensagem.conversation_id == conversa_do_outro.pk
    assert Message.objects.count() == 2


def test_titulo_da_conversa_vem_da_primeira_pergunta(conversa):
    ingest_inbound_message(conversa, _inbound(conversa, texto="sell-out de julho"))
    ingest_inbound_message(conversa, _inbound(conversa, texto="e em agosto?", client_id="c-2"))

    conversa.refresh_from_db()
    assert conversa.title == "sell-out de julho"


def test_resposta_entregue_fica_registrada_como_enviada(conversa):
    canal = FakeChannel()

    mensagem = deliver_reply(canal, conversa, "foram 1.234 unidades")

    assert mensagem.direction == Message.Direction.OUTBOUND
    assert mensagem.status == Message.Status.SENT
    assert canal.delivered == [(conversa.pk, "foram 1.234 unidades")]


class _CanalQueFalha(FakeChannel):
    def deliver(self, conversation, text):
        raise ConnectionError("falha simulada na entrega")


class _CanalQueRecusa(FakeChannel):
    def deliver(self, conversation, text):
        return DeliveryResult(delivered=False, detail="canal indisponível")


@pytest.mark.parametrize("canal", [_CanalQueFalha(), _CanalQueRecusa()])
def test_falha_na_entrega_nao_estoura_e_fica_registrada(conversa, canal):
    """Se a exceção subisse, a resposta e a auditoria não seriam gravadas e o
    usuário ficaria sem nada e sem rastro — o oposto do que se quer numa
    falha de canal."""
    mensagem = deliver_reply(canal, conversa, "resposta")

    assert mensagem.status == Message.Status.FAILED
    assert mensagem.delivery_detail
