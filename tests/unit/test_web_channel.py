"""Canal do chat web: o que entra pela API vira InboundMessage."""

import pytest

from messaging.channels.fake import FakeChannel
from messaging.channels.web import MAX_QUESTION_CHARS, WebChannel


def _payload(**overrides):
    payload = {
        "conversation_id": 7,
        "client_message_id": "  c-1  ",
        "text": "  unidades de Extrato em 2026  ",
    }
    payload.update(overrides)
    return payload


def test_normaliza_espacos_da_pergunta_e_do_identificador():
    inbound = WebChannel().parse_inbound(_payload())

    assert inbound.conversation_id == 7
    assert inbound.client_message_id == "c-1"
    assert inbound.text == "unidades de Extrato em 2026"


def test_campo_obrigatorio_ausente_vira_key_error():
    payload = _payload()
    del payload["text"]

    with pytest.raises(KeyError):
        WebChannel().parse_inbound(payload)


@pytest.mark.parametrize("texto", ["", "   ", "\n"])
def test_pergunta_vazia_e_recusada(texto):
    """Pergunta em branco gastaria uma chamada de IA para nada."""
    with pytest.raises(ValueError):
        WebChannel().parse_inbound(_payload(text=texto))


def test_pergunta_longa_demais_e_recusada():
    """Texto colado por engano — ou empurrado de propósito — encheria o
    contexto do modelo e o custo junto."""
    with pytest.raises(ValueError):
        WebChannel().parse_inbound(_payload(text="a" * (MAX_QUESTION_CHARS + 1)))


def test_identificador_vazio_e_recusado():
    """Sem identificador não há idempotência: um reenvio viraria outra
    pergunta."""
    with pytest.raises(ValueError):
        WebChannel().parse_inbound(_payload(client_message_id="  "))


def test_canal_fake_guarda_o_que_seria_entregue(db, django_user_model):
    """O fake permite um teste afirmar que NADA chegou ao usuário — coisa que
    o canal web não deixa observar, porque lá entregar é gravar no banco."""
    from conversations.models import Conversation

    user = django_user_model.objects.create_user("ana", password="x")
    conversation = Conversation.objects.create(user=user)
    channel = FakeChannel()

    channel.deliver(conversation, "resposta")

    assert channel.delivered == [(conversation.pk, "resposta")]
