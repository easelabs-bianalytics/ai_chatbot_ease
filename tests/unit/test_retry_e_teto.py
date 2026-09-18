"""Retry do provedor e teto de gasto mensal (ADR-0005, ADR-0016, O-14)."""

import datetime
from decimal import Decimal

import pytest

from ai_orchestrator import budget
from ai_orchestrator.models import AIReply
from ai_orchestrator.providers.base import AIProviderError, PlanRequest
from ai_orchestrator.providers.retrying import RetryingAIProvider
from tests.fakes.providers import ScriptedAIProvider, plano


def _pedido():
    return PlanRequest(question="quantas unidades em agosto de 2026?")


def test_falha_passageira_nao_chega_ao_usuario():
    """Limite de requisições e queda de conexão são rotina numa API externa;
    sem o retry viravam "tive um problema técnico"."""
    esperas = []
    inner = ScriptedAIProvider([AIProviderError("429 rate limit"), plano()])

    provider = RetryingAIProvider(inner, dormir=esperas.append)
    resultado = provider.plan(_pedido())

    assert resultado.sql
    assert esperas == [1.0]


def test_espera_cresce_a_cada_tentativa():
    esperas = []
    inner = ScriptedAIProvider([AIProviderError("1"), AIProviderError("2"), plano()])

    RetryingAIProvider(inner, dormir=esperas.append).plan(_pedido())

    assert esperas == [1.0, 2.0]


def test_falha_que_persiste_sobe_para_o_orquestrador():
    """Insistir para sempre seguraria a tarefa e gastaria a cada tentativa."""
    inner = ScriptedAIProvider([AIProviderError("fora do ar")] * 3)

    with pytest.raises(AIProviderError, match="fora do ar"):
        RetryingAIProvider(inner, dormir=lambda _: None).plan(_pedido())


def test_modelo_do_provedor_interno_continua_visivel():
    """O relatório e o `chat_local` mostram o modelo; o embrulho não pode
    escondê-lo."""

    class Interno(ScriptedAIProvider):
        model = "gpt-5.6-terra"
        answer_model = "gpt-5.6-luna"

    provider = RetryingAIProvider(Interno([plano()]))

    assert provider.model == "gpt-5.6-terra"
    assert provider.answer_model == "gpt-5.6-luna"


# --- teto de gasto --------------------------------------------------------


@pytest.mark.django_db
def test_sem_variavel_nao_ha_teto(monkeypatch):
    monkeypatch.delenv(budget.VARIAVEL, raising=False)

    assert budget.teto() is None
    assert budget.excedido() is False


def test_valor_invalido_nao_vira_teto_de_zero(monkeypatch):
    """Um teto lido errado como zero bloquearia o chatbot inteiro."""
    monkeypatch.setenv(budget.VARIAVEL, "cem dólares")

    assert budget.teto() is None


def test_teto_aceita_virgula(monkeypatch):
    monkeypatch.setenv(budget.VARIAVEL, "12,50")

    assert budget.teto() == Decimal("12.50")


@pytest.mark.django_db
def test_gasto_do_mes_soma_so_o_mes_corrente(monkeypatch, django_user_model):
    from conversations.models import Conversation
    from messaging.models import Message

    conversa = Conversation.objects.create(user=django_user_model.objects.create_user("ana"))
    for indice, custo in enumerate((Decimal("0.02"), Decimal("0.03"))):
        mensagem = Message.objects.create(
            conversation=conversa,
            direction=Message.Direction.INBOUND,
            content="p",
            client_message_id=f"c-{indice}",
        )
        AIReply.objects.create(message=mensagem, decision=AIReply.Decision.ANSWERED, cost_estimate=custo)

    antiga = AIReply.objects.order_by("id").first()  # ordering do modelo é decrescente
    AIReply.objects.filter(pk=antiga.pk).update(
        created_at=datetime.datetime(2020, 1, 5, tzinfo=datetime.timezone.utc)
    )

    assert budget.gasto_do_mes() == Decimal("0.03")


@pytest.mark.django_db
def test_situacao_avisa_quando_passa_de_oitenta_por_cento(monkeypatch, django_user_model):
    from conversations.models import Conversation
    from messaging.models import Message

    monkeypatch.setenv(budget.VARIAVEL, "1")
    conversa = Conversation.objects.create(user=django_user_model.objects.create_user("ana"))
    mensagem = Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND, content="p", client_message_id="c"
    )
    AIReply.objects.create(
        message=mensagem, decision=AIReply.Decision.ANSWERED, cost_estimate=Decimal("0.85")
    )

    situacao = budget.situacao()

    assert situacao["perto_do_limite"] is True
    assert situacao["excedido"] is False


def test_sem_credito_nao_e_repetido():
    """Crédito esgotado não volta sozinho: insistir só atrasaria o aviso."""
    from ai_orchestrator.providers.base import AIQuotaExceeded

    esperas = []
    inner = ScriptedAIProvider([AIQuotaExceeded("insufficient_quota"), plano()])

    with pytest.raises(AIQuotaExceeded):
        RetryingAIProvider(inner, dormir=esperas.append).plan(_pedido())
    assert esperas == []
