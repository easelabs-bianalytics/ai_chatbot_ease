"""O que a tela recebe de uma investigação (ADR-0025)."""

import pytest
from rest_framework.test import APIClient

from ai_orchestrator import progresso
from conversations.models import Conversation
from datasource.executors.fake import FakeQueryExecutor
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider
from tests.unit.test_investigacao import POR_GR, PERGUNTA, _analise, _conclui, _investiga, _passo
from tests.unit.test_orchestrator import _responder, catalogo  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(django_user_model):
    return django_user_model.objects.create_user("ana", password="x")


@pytest.fixture
def cliente(ana):
    cliente = APIClient()
    cliente.force_authenticate(ana)
    return cliente


@pytest.fixture
def conversa(ana):
    return Conversation.objects.create(user=ana)


def _pergunta(conversa):
    return Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND, content=PERGUNTA, client_message_id="c-1",
    )


def test_resposta_da_investigacao_traz_blocos_hipoteses_e_nao_oferece_excel(cliente, conversa, catalogo):
    blocos = (
        {"tipo": "texto", "texto": "A queda foi concentrada no GR Sul."},
        {"tipo": "tabela", "consulta": 0, "colunas": ["gr", "var_pct"]},
    )
    provider = ScriptedAIProvider(
        [_investiga(_passo("foi concentrada?")), _conclui()],
        [_analise("A queda foi concentrada no GR Sul.", blocos=blocos)],
    )
    _responder(_pergunta(conversa), catalogo, provider=provider, executor=FakeQueryExecutor([POR_GR]))

    resposta = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"][1]
    fonte = resposta["fonte"]

    assert [b["tipo"] for b in fonte["blocos"]] == ["texto", "tabela"]
    assert fonte["dados_blocos"]["0"]["columns"] == ["gr", "var_und", "var_pct"]
    assert fonte["investigacao"][0]["hipotese"] == "foi concentrada?"
    # A planilha sairia de uma consulta só, escolhida ao acaso.
    assert fonte["excel"] is False


def test_pergunta_pendente_mostra_o_que_o_jarvis_esta_fazendo(cliente, conversa):
    pergunta = _pergunta(conversa)
    progresso.definir(pergunta.pk, "Testando: a queda foi concentrada?")

    dados = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"][0]

    assert dados["progresso"] == "Testando: a queda foi concentrada?"


def test_pergunta_respondida_nao_mostra_progresso(cliente, conversa):
    pergunta = _pergunta(conversa)
    Message.objects.filter(pk=pergunta.pk).update(status=Message.Status.PROCESSED)
    progresso.definir(pergunta.pk, "sobrou")

    dados = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"][0]

    assert "progresso" not in dados
