"""Nunca mostrar erro ao usuário (2026-10-01).

Conversa 40: o rascunho reprovado pela ancoragem dizia "há uma inconsistência
no resultado, a comparação deve ser refeita"; o texto gravado era o
reescrito, mas a tela desenhou os blocos do rascunho.

Áudio do Fernando (conversa 41, 2026-09-29): as duas consultas da "rodada
final" de uma investigação estouraram o tempo do banco, a investigação parou
sem tentar de novo e respondeu "tente com o período e o recorte mais
específicos" — culpando o pedido por um limite nosso.
"""

import pytest

from ai_orchestrator import canned
from ai_orchestrator.orchestrator import DICA_DO_TEMPO, handle_message
from ai_orchestrator.providers.base import Plan
from catalog.loader import load_catalog
from conversations.models import Conversation
from datasource.executors.base import QueryTimeout
from datasource.executors.fake import FakeQueryExecutor, make_result
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta

pytestmark = pytest.mark.django_db

RESULTADO = make_result(("periodo", "unidades", "variacao"), [("set/26", 4798, -375), ("ago/26", 5172, None)])


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


@pytest.fixture
def pergunta(django_user_model):
    user = django_user_model.objects.create_user("rubens", password="x")
    conversa = Conversation.objects.create(user=user)
    return Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND,
        content="me passa o sell-out parcial de setembro contra agosto", client_message_id="c-1",
    )


def _responder(mensagem, catalogo, provider, executor):
    return handle_message(mensagem, channel=FakeChannel(), provider=provider, executor=executor, catalog=catalogo)


def test_tela_mostra_os_blocos_da_versao_aprovada(pergunta, catalogo):
    reprovado = "Há uma inconsistência: a diferença dá 374, a comparação deve ser refeita."
    aprovado = "Setembro tem 4.798 unidades contra 5.172 em agosto: variação de -375."
    provider = ScriptedAIProvider(
        [plano()],
        [
            resposta(reprovado, blocos=({"tipo": "texto", "texto": reprovado},), followups=("Refaz a variação",)),
            resposta(aprovado, blocos=({"tipo": "texto", "texto": aprovado},), followups=("E em julho?",)),
        ],
    )

    reply = _responder(pergunta, catalogo, provider, FakeQueryExecutor([RESULTADO]))

    textos = [b["texto"] for b in reply.raw_response["blocos"] if b["tipo"] == "texto"]
    assert textos == [aprovado]
    assert reply.raw_response["sugestoes"] == ["E em julho?"]
    assert reply.raw_response["rascunho_reprovado"] == [reprovado]


def test_dois_rascunhos_reprovados_nao_deixam_bloco_de_nenhum(pergunta, catalogo):
    ruim = "A comparação deve ser refeita: a diferença dá 374."
    provider = ScriptedAIProvider(
        [plano()],
        [resposta(ruim, blocos=({"tipo": "texto", "texto": ruim},)),
         resposta(ruim, blocos=({"tipo": "texto", "texto": ruim},))],
    )

    reply = _responder(pergunta, catalogo, provider, FakeQueryExecutor([RESULTADO]))

    assert "blocos" not in reply.raw_response
    assert "refeita" not in reply.reply_text


def _investigacao(*passos, rodada_final=False):
    return plano("", intent=Plan.Intent.INVESTIGATE, rodada_final=rodada_final, investigacao=tuple(
        {"hipotese": h, "sql": "SELECT 1 FROM cddd.vendas_consolidado", "reference_query_id": ""} for h in passos
    ))


def test_rodada_final_que_estourou_o_tempo_ganha_outra_rodada(pergunta, catalogo):
    tempo = QueryTimeout("a consulta passou de 15000 ms e foi cancelada")
    achado = make_result(("laboratorio", "share"), [("Greencare", 18.2)])
    provider = ScriptedAIProvider(
        [_investigacao("as 3 piores quedas", "quem ganhou share", rodada_final=True),
         _investigacao("quem ganhou share, com os 3 nomes num VALUES", rodada_final=True)],
        [resposta("A Greencare ganhou 18,2 de share.")],
    )

    reply = _responder(pergunta, catalogo, provider, FakeQueryExecutor([tempo, tempo, achado]))

    assert len(provider.plan_requests) == 2
    assert DICA_DO_TEMPO.strip() in provider.plan_requests[1].achados
    assert reply.reply_text.startswith("A Greencare")


def test_investigacao_pesada_nao_culpa_o_pedido(pergunta, catalogo):
    tempo = QueryTimeout("a consulta passou de 15000 ms e foi cancelada")
    provider = ScriptedAIProvider([_investigacao("h1", rodada_final=True)] * 3)

    reply = _responder(pergunta, catalogo, provider, FakeQueryExecutor([tempo] * 6))

    assert reply.reply_text == canned.INVESTIGACAO_PESADA
    assert "Tente" not in reply.reply_text and "erro" not in reply.reply_text.lower()


def test_rodada_sem_dado_passa_pelo_teto_por_pergunta(pergunta, catalogo, monkeypatch):
    """O teto de US$ 0,15 por pergunta corta as rodadas opcionais. A que só
    existe porque nada trouxe dado não é opcional: o planejamento da
    pergunta do Fernando sozinho custou US$ 0,20."""
    monkeypatch.setenv("AI_MAX_COST_PER_QUESTION", "0.0001")
    tempo = QueryTimeout("a consulta passou de 60000 ms e foi cancelada")
    achado = make_result(("laboratorio", "share"), [("Greencare", 18.2)])
    provider = ScriptedAIProvider(
        [_investigacao("h1", rodada_final=True), _investigacao("h1 mais leve", rodada_final=True)],
        [resposta("A Greencare ganhou 18,2 de share.")],
    )

    reply = _responder(pergunta, catalogo, provider, FakeQueryExecutor([tempo, achado]))

    assert len(provider.plan_requests) == 2
    assert reply.reply_text.startswith("A Greencare")
