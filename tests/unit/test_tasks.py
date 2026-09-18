"""Tarefa Celery e escolha de provedor/executor por ambiente."""

import pytest

from ai_orchestrator.models import AIReply
from ai_orchestrator.provider_factory import get_configured_provider
from ai_orchestrator.providers.fake import FakeAIProvider
from ai_orchestrator.tasks import process_message
from conversations.models import Conversation
from datasource.executors.factory import get_configured_executor
from datasource.executors.fake import FakeQueryExecutor
from datasource.executors.postgres_readonly import PostgresReadOnlyExecutor
from messaging.models import Message

pytestmark = pytest.mark.django_db


def test_sem_credencial_do_banco_de_negocio_o_executor_e_o_fake():
    """Configuração faltando não pode virar conexão acidental em outro lugar,
    nem erro no meio da resposta ao usuário."""
    assert isinstance(get_configured_executor(), FakeQueryExecutor)


def test_com_credencial_o_executor_e_o_somente_leitura(monkeypatch):
    monkeypatch.setenv("ANALYTICS_DATABASE_URL", "postgresql://u:p@localhost:5435/analytics")

    assert isinstance(get_configured_executor(), PostgresReadOnlyExecutor)


def test_provedor_padrao_e_o_fake():
    assert isinstance(get_configured_provider(), FakeAIProvider)


def test_provedor_openai_vem_embrulhado_no_retry(monkeypatch):
    """Falha de rede na OpenAI é rotina; sem o retry ela viraria "tive um
    problema técnico" na cara do usuário (ADR-0016)."""
    from ai_orchestrator.providers.openai_provider import OpenAIProvider
    from ai_orchestrator.providers.retrying import RetryingAIProvider

    monkeypatch.setenv("AI_PROVIDER", "openai")

    provider = get_configured_provider()

    assert isinstance(provider, RetryingAIProvider)
    assert isinstance(provider._inner, OpenAIProvider)


def test_provedor_desconhecido_falha_alto(monkeypatch):
    """Melhor não subir do que responder com um provedor que ninguém
    configurou."""
    monkeypatch.setenv("AI_PROVIDER", "vertex")

    with pytest.raises(NotImplementedError):
        get_configured_provider()


def test_tarefa_processa_a_pergunta_e_devolve_a_resposta(django_user_model):
    conversa = Conversation.objects.create(
        user=django_user_model.objects.create_user("ana", password="x")
    )
    mensagem = Message.objects.create(
        conversation=conversa,
        direction=Message.Direction.INBOUND,
        content="o que você sabe responder?",
        client_message_id="c-1",
        status=Message.Status.RECEIVED,
    )

    reply_id = process_message(mensagem.pk, "fake")

    assert AIReply.objects.get(pk=reply_id).message_id == mensagem.pk
    mensagem.refresh_from_db()
    assert mensagem.status == Message.Status.PROCESSED


def test_numero_de_tentativas_vem_do_ambiente(monkeypatch):
    """A variável estava documentada no `.env.example` e ninguém a lia: o
    operador ajustava e nada mudava."""
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_PROVIDER_MAX_ATTEMPTS", "5")

    assert get_configured_provider()._tentativas == 5


def test_tentativas_invalidas_caem_no_padrao(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_PROVIDER_MAX_ATTEMPTS", "muitas")

    assert get_configured_provider()._tentativas == 3
