"""API do chat: login, idempotência, isolamento entre usuários e polling."""

import pytest
from rest_framework.test import APIClient

from ai_orchestrator.models import AIReply
from conversations.models import Conversation
from messaging.models import Message

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(django_user_model):
    return django_user_model.objects.create_user("ana", password="x")


@pytest.fixture
def cliente(usuario):
    client = APIClient()
    client.force_login(usuario)
    return client


def _nova_conversa(cliente):
    return cliente.post("/api/conversations/", {}, format="json").json()["id"]


def _pergunta(**overrides):
    payload = {"client_message_id": "c-1", "text": "unidades de Extrato em 2026"}
    payload.update(overrides)
    return payload


def test_chat_exige_login():
    """O chat expõe dado de negócio e gasta API paga: nada aqui é público."""
    anonimo = APIClient()

    assert anonimo.get("/api/conversations/").status_code == 403
    assert anonimo.post("/api/conversations/", {}, format="json").status_code == 403


def test_lista_traz_somente_as_conversas_do_usuario(cliente, django_user_model):
    minha = _nova_conversa(cliente)
    outro = django_user_model.objects.create_user("bruno", password="x")
    Conversation.objects.create(user=outro, title="conversa do bruno")

    listadas = cliente.get("/api/conversations/").json()["conversations"]

    assert [c["id"] for c in listadas] == [minha]


def test_pergunta_e_aceita_e_fica_registrada(cliente):
    conversa_id = _nova_conversa(cliente)

    resposta = cliente.post(
        f"/api/conversations/{conversa_id}/messages/", _pergunta(), format="json"
    )

    assert resposta.status_code == 202
    assert resposta.json()["created"] is True
    mensagem = Message.objects.get(direction=Message.Direction.INBOUND)
    assert mensagem.content == "unidades de Extrato em 2026"
    assert Conversation.objects.get(pk=conversa_id).title == "unidades de Extrato em 2026"


def test_pergunta_reenviada_nao_gera_segundo_processamento(cliente):
    """Clique duplo e reenvio por rede ruim são o caso comum no chat: a
    segunda chamada devolve a mesma mensagem, sem criar outra."""
    conversa_id = _nova_conversa(cliente)
    url = f"/api/conversations/{conversa_id}/messages/"

    primeira = cliente.post(url, _pergunta(), format="json")
    segunda = cliente.post(url, _pergunta(), format="json")

    assert primeira.status_code == 202
    assert segunda.status_code == 200
    assert segunda.json()["created"] is False
    assert segunda.json()["message_id"] == primeira.json()["message_id"]
    assert Message.objects.filter(direction=Message.Direction.INBOUND).count() == 1
    # E, principalmente, nenhuma segunda resposta foi produzida.
    assert AIReply.objects.count() == 1


@pytest.mark.parametrize(
    "payload, motivo",
    [
        ({"client_message_id": "c-1", "text": "   "}, "pergunta vazia"),
        ({"text": "sem identificador"}, "campo obrigatório ausente"),
    ],
)
def test_payload_invalido_e_recusado(cliente, payload, motivo):
    conversa_id = _nova_conversa(cliente)

    resposta = cliente.post(
        f"/api/conversations/{conversa_id}/messages/", payload, format="json"
    )

    assert resposta.status_code == 400
    assert Message.objects.count() == 0


def test_conversa_de_outro_usuario_responde_404(cliente, django_user_model):
    """404, e não 403: um 403 confirmaria que a conversa existe."""
    outro = django_user_model.objects.create_user("bruno", password="x")
    alheia = Conversation.objects.create(user=outro)
    url = f"/api/conversations/{alheia.pk}/messages/"

    assert cliente.get(url).status_code == 404
    assert cliente.post(url, _pergunta(), format="json").status_code == 404
    assert Message.objects.count() == 0


def test_polling_traz_apenas_as_mensagens_novas(cliente):
    """O navegador busca a partir do que já tem; sem isso o chat recarregaria
    a conversa inteira a cada poucos segundos."""
    conversa_id = _nova_conversa(cliente)
    url = f"/api/conversations/{conversa_id}/messages/"
    primeira = cliente.post(url, _pergunta(), format="json").json()["message_id"]
    cliente.post(url, _pergunta(client_message_id="c-2", text="e em agosto?"), format="json")

    novas = [m["text"] for m in cliente.get(f"{url}?after={primeira}").json()["messages"]]

    assert "e em agosto?" in novas
    assert "unidades de Extrato em 2026" not in novas


def test_after_invalido_e_recusado(cliente):
    conversa_id = _nova_conversa(cliente)

    resposta = cliente.get(f"/api/conversations/{conversa_id}/messages/?after=abc")

    assert resposta.status_code == 400


def test_pergunta_enviada_recebe_resposta_no_polling(cliente):
    """Caminho completo com a fila em modo eager: a API aceita, o orquestrador
    responde e a resposta aparece para o navegador na próxima busca."""
    conversa_id = _nova_conversa(cliente)
    url = f"/api/conversations/{conversa_id}/messages/"

    envio = cliente.post(url, _pergunta(text="o que você sabe responder?"), format="json")

    assert envio.status_code == 202
    mensagens = cliente.get(url).json()["messages"]
    assert [m["direction"] for m in mensagens] == ["in", "out"]
    assert mensagens[1]["text"]
    assert Message.objects.get(pk=envio.json()["message_id"]).ai_reply
