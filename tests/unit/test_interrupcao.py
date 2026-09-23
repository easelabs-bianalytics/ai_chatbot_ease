"""Interromper uma pergunta em andamento.

O ponto da funcionalidade é dinheiro: chamada que já saiu está paga, mas a
parada evita as que viriam depois — a redação de toda pergunta, e as rodadas
seguintes de uma investigação, que são o gasto grande.

O que estes testes fixam:

1. parada antes de tudo não chama o modelo nem o banco — zero;
2. parada depois do plano não chama a redação;
3. parada no meio da investigação não abre a rodada seguinte;
4. a pergunta interrompida **continua na auditoria com o custo já gasto**,
   senão o `bi_report` mente sobre o mês;
5. resposta que ficou pronta no mesmo instante do clique é descartada;
6. interromper o que já terminou não desfaz nada.
"""

import pytest

from ai_orchestrator.models import AICall, AIReply
from ai_orchestrator.orchestrator import handle_message
from ai_orchestrator.providers.base import Plan
from catalog.loader import load_catalog
from conversations.models import Conversation
from datasource.executors.fake import FakeQueryExecutor, make_result
from datasource.models import QueryRun
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta

pytestmark = pytest.mark.django_db

RESULTADO = make_result(("rede", "unidades"), [("Pague Menos", 47.0)])


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


@pytest.fixture
def conversa(django_user_model):
    user = django_user_model.objects.create_user("ana", password="x")
    return Conversation.objects.create(user=user)


def _pergunta(conversa, status=Message.Status.RECEIVED, texto="quantas unidades a Pague Menos vendeu em agosto de 2026?"):
    return Message.objects.create(
        conversation=conversa,
        direction=Message.Direction.INBOUND,
        content=texto,
        client_message_id="c-1",
        status=status,
    )


def _responder(mensagem, catalogo, provider, executor=None):
    return handle_message(
        mensagem,
        channel=FakeChannel(),
        provider=provider,
        executor=executor or FakeQueryExecutor([RESULTADO]),
        catalog=catalogo,
    )


def test_parada_na_fila_nao_chama_nada(conversa, catalogo):
    """Interrompida antes de o worker pegar: nenhuma chamada, nenhum gasto."""
    mensagem = _pergunta(conversa, status=Message.Status.CANCELLED)
    provider = ScriptedAIProvider([plano(sql="SELECT 1")], [resposta("47 unidades")])
    executor = FakeQueryExecutor([RESULTADO])

    reply = _responder(mensagem, catalogo, provider, executor)

    assert reply.decision == AIReply.Decision.CANCELLED
    assert provider.plan_requests == []
    assert executor.executed == []
    assert AICall.objects.count() == 0
    assert reply.cost_estimate in (None, 0)


def test_parada_depois_do_plano_nao_chama_a_redacao(conversa, catalogo):
    """O plano já está pago quando volta; o que a parada evita é a redação."""
    mensagem = _pergunta(conversa)
    provider = ScriptedAIProvider([plano(sql="SELECT 1")], [resposta("47 unidades")])

    def parar_depois_do_plano(_request):
        Message.objects.filter(pk=mensagem.pk).update(status=Message.Status.CANCELLED)

    provider.ao_planejar = parar_depois_do_plano

    reply = _responder(mensagem, catalogo, provider)

    assert reply.decision == AIReply.Decision.CANCELLED
    assert provider.answer_requests == []
    # O que já tinha sido gasto continua registrado: é o que mantém o
    # relatório de custo honesto.
    assert list(AICall.objects.values_list("stage", flat=True)) == [AICall.Stage.PLAN]


def test_pergunta_interrompida_nao_recebe_resposta_na_conversa(conversa, catalogo):
    mensagem = _pergunta(conversa, status=Message.Status.CANCELLED)

    _responder(mensagem, catalogo, ScriptedAIProvider([plano(sql="SELECT 1")]))

    assert not Message.objects.filter(direction=Message.Direction.OUTBOUND).exists()
    mensagem.refresh_from_db()
    assert mensagem.status == Message.Status.CANCELLED


def test_resposta_que_ficou_pronta_junto_com_o_clique_e_descartada(conversa, catalogo):
    """A corrida: a redação terminou no mesmo instante da parada. Quem
    apertou parar não quer ler a resposta."""
    mensagem = _pergunta(conversa)
    provider = ScriptedAIProvider([plano(sql="SELECT 1")], [resposta("47 unidades")])

    def parar_depois_de_redigir(_request):
        Message.objects.filter(pk=mensagem.pk).update(status=Message.Status.CANCELLED)

    provider.ao_responder = parar_depois_de_redigir

    reply = _responder(mensagem, catalogo, provider)

    assert reply.decision == AIReply.Decision.CANCELLED
    assert reply.reply_text == ""
    assert not Message.objects.filter(direction=Message.Direction.OUTBOUND).exists()
    # As duas chamadas aconteceram e estão na conta.
    assert AICall.objects.count() == 2


def test_parada_no_meio_da_investigacao_nao_abre_a_rodada_seguinte(conversa, catalogo):
    """Onde a parada economiza de verdade.

    Cada rodada custa uma chamada ao planejador e até quatro consultas, e a
    análise final vem depois de todas. Parar na primeira rodada evita o
    resto — foi o caso que motivou o botão.
    """
    mensagem = _pergunta(conversa, texto="Porque a Ease Labs caiu em Sell Out em jul/26?")
    passo = {"hipotese": "a queda foi concentrada num GR?", "sql": "SELECT und FROM cddd.vendas_consolidado"}
    provider = ScriptedAIProvider(
        [plano(sql="", intent=Plan.Intent.INVESTIGATE, investigacao=(passo, passo))],
        [resposta("a queda foi no GR Sul")],
    )

    def parar_ao_planejar(_request):
        Message.objects.filter(pk=mensagem.pk).update(status=Message.Status.CANCELLED)

    provider.ao_planejar = parar_ao_planejar

    reply = _responder(mensagem, catalogo, provider, FakeQueryExecutor([RESULTADO, RESULTADO]))

    assert reply.decision == AIReply.Decision.CANCELLED
    # Nenhuma hipótese foi testada e a análise nunca foi escrita.
    assert QueryRun.objects.count() == 0
    assert provider.answer_requests == []
    assert len(provider.plan_requests) == 1
