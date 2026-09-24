"""Crítica à resposta anterior refaz na hora (conversa 22, 2026-09-24).

"Veja o visual que criou, que coisa feia!!", com o print do gráfico, voltou
como leitura de imagem: o Jarvis concordou, descreveu o que faria e só
entregou o gráfico corrigido quando a pessoa pediu "Faça então amigo!! por
favor". Crítica é pedido de correção, com ou sem print.
"""

import pytest

from ai_orchestrator import autocritica
from ai_orchestrator.models import AIReply
from ai_orchestrator.providers.base import Plan
from attachments import deposito
from datasource.executors.fake import FakeQueryExecutor
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, leitura, plano, resposta
from tests.unit.test_orchestrator_anexos import RESULTADO, _responder, catalogo, conversa  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "mensagem",
    [
        "Veja o visual que criou, que coisa feia!!",
        "está errado, a tendência não ficou certa",
        "não era isso que eu pedi",
        "corrige o gráfico, os rótulos estão sobrepostos",
        "refaça por favor",
    ],
)
def test_reconhece_a_critica(mensagem):
    assert autocritica.e_critica(mensagem)


@pytest.mark.parametrize(
    "mensagem",
    [
        "Quantas unidades a Ease vendeu em agosto de 2026?",
        "qual o melhor mês de 2026?",
        "Faça então amigo!! por favor",
        "",
    ],
)
def test_pergunta_comum_nao_e_critica(mensagem):
    assert not autocritica.e_critica(mensagem)


def _mensagem(conversa, texto, client_id, imagem=False):
    extras = {}
    if imagem:
        extras = {"anexo_tipo": Message.Anexo.IMAGEM, "anexo_nome": "print.png",
                  "anexo_resumo": "imagem", "anexo_token": deposito.guardar(b"png")}
    return Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND, content=texto,
        client_message_id=client_id, status=Message.Status.RECEIVED, **extras,
    )


def _resposta_com_dado(conversa, catalogo):
    _responder(
        _mensagem(conversa, "unidades por rede em agosto de 2026", "c-0"), catalogo,
        ScriptedAIProvider([plano()], [resposta("A Pague Menos vendeu 47 unidades.")]),
        FakeQueryExecutor([RESULTADO]),
    )


def test_critica_em_texto_chega_ao_planejador_com_o_aviso(conversa, catalogo):
    _resposta_com_dado(conversa, catalogo)
    provider = ScriptedAIProvider([plano()], [resposta("A Pague Menos vendeu 47 unidades.")])

    _responder(_mensagem(conversa, "que coisa feia!! está errado", "c-1"), catalogo,
               provider, FakeQueryExecutor([RESULTADO]))

    assert provider.plan_requests[0].autocritica_note == autocritica.NOTA_DA_CRITICA


def test_critica_respondida_com_conversa_ganha_segunda_chance(conversa, catalogo):
    _resposta_com_dado(conversa, catalogo)
    provider = ScriptedAIProvider(
        [plano(intent=Plan.Intent.CONVERSATION, user_message="Você tem razão, ficou ruim."), plano()],
        [resposta("A Pague Menos vendeu 47 unidades.")],
    )

    reply = _responder(_mensagem(conversa, "que coisa feia!!", "c-1"), catalogo,
                       provider, FakeQueryExecutor([RESULTADO]))

    assert len(provider.plan_requests) == 2
    assert "só com conversa" in provider.plan_requests[1].autocritica_note
    assert reply.decision == AIReply.Decision.ANSWERED


def test_print_com_critica_refaz_em_vez_de_so_ler(conversa, catalogo):
    """A conversa 22 exata: o print com "que coisa feia!!"."""
    _resposta_com_dado(conversa, catalogo)
    provider = ScriptedAIProvider(
        [plano()], [resposta("A Pague Menos vendeu 47 unidades.")],
        leituras=[leitura(resposta="As barras estão finas e a tendência está quase horizontal.")],
    )

    reply = _responder(_mensagem(conversa, "Veja o visual que criou, que coisa feia!!", "c-1", imagem=True),
                       catalogo, provider, FakeQueryExecutor([RESULTADO]))

    assert reply.decision == AIReply.Decision.ANSWERED
    assert "barras estão finas" in provider.plan_requests[0].question
    assert provider.plan_requests[0].autocritica_note == autocritica.NOTA_DA_CRITICA
    assert reply.raw_response["imagem"]["virou"] == "correcao"


def test_critica_sem_resposta_anterior_com_dado_segue_normal(conversa, catalogo):
    provider = ScriptedAIProvider([plano(intent=Plan.Intent.CONVERSATION, user_message="Oi!")], [])

    _responder(_mensagem(conversa, "que coisa feia", "c-1"), catalogo, provider, FakeQueryExecutor())

    assert len(provider.plan_requests) == 1
    assert provider.plan_requests[0].autocritica_note == ""
