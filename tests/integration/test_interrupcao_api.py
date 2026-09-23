"""Endpoint de interromper uma pergunta.

Ele só escreve o status; quem para de fato é o worker, que o lê entre as
etapas. Por isso o que importa aqui é quem pode escrever, sobre o quê, e o
que acontece quando a resposta chega no mesmo instante.
"""

import pytest
from rest_framework.test import APIClient

from conversations.models import Conversation
from messaging.models import Message

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(django_user_model):
    return django_user_model.objects.create_user("ana", email="ana@easelabs.com.br", password="x")


@pytest.fixture
def cliente(ana):
    cliente = APIClient()
    cliente.force_authenticate(ana)
    return cliente


@pytest.fixture
def conversa(ana):
    return Conversation.objects.create(user=ana)


def _pergunta(conversa, status=Message.Status.PROCESSING):
    return Message.objects.create(
        conversation=conversa,
        direction=Message.Direction.INBOUND,
        content="quantas unidades?",
        client_message_id="c-1",
        status=status,
    )


def _url(conversa, mensagem):
    return f"/api/conversations/{conversa.pk}/messages/{mensagem.pk}/interromper/"


def test_interrompe_pergunta_em_processamento(cliente, conversa):
    mensagem = _pergunta(conversa)

    resposta = cliente.post(_url(conversa, mensagem), {}, format="json")

    assert resposta.status_code == 200
    assert resposta.json()["interrompida"] is True
    mensagem.refresh_from_db()
    assert mensagem.status == Message.Status.CANCELLED


def test_pergunta_ja_respondida_nao_e_desfeita(cliente, conversa):
    """A corrida vista do outro lado: se a resposta ficou pronta um instante
    antes do clique, o status já não é mais de trabalho em curso e nada
    muda — a resposta entregue continua valendo."""
    mensagem = _pergunta(conversa, status=Message.Status.PROCESSED)

    resposta = cliente.post(_url(conversa, mensagem), {}, format="json")

    assert resposta.json()["interrompida"] is False
    mensagem.refresh_from_db()
    assert mensagem.status == Message.Status.PROCESSED


def test_conversa_de_outra_pessoa_nao_pode_ser_interrompida(cliente, django_user_model):
    bia = django_user_model.objects.create_user("bia", password="x")
    conversa_da_bia = Conversation.objects.create(user=bia)
    mensagem = _pergunta(conversa_da_bia)

    resposta = cliente.post(_url(conversa_da_bia, mensagem), {}, format="json")

    assert resposta.status_code == 404
    mensagem.refresh_from_db()
    assert mensagem.status == Message.Status.PROCESSING


def test_o_status_interrompida_chega_na_tela(cliente, conversa):
    """A tela precisa saber, ao reabrir a conversa, que aquela pergunta foi
    interrompida — senão ela volta a esperar uma resposta que não vem."""
    mensagem = _pergunta(conversa, status=Message.Status.CANCELLED)

    dados = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()

    assert [m["status"] for m in dados["messages"] if m["id"] == mensagem.pk] == ["cancelled"]
