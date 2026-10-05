"""Pergunta sem referência: reconhecer o dado antes de responder (ADR-0033).

O caso de origem é a conversa 70 (Amanda, 2026-10-05): "os pacientes que
aderiram ao PBM e concluíram a transação". Sem referência, o Jarvis escreveu
a consulta às cegas — contou adesões em vez de pacientes, não viu que
outubro não tinha entrado, não disse o critério, e a consulta procurava a
transação adesão por adesão. O método que resolveu: frescor, grão e chave,
valores e o tamanho de cada leitura, numa rodada de consultas pequenas, e
só depois a consulta final com as premissas.
"""

import pytest

from ai_orchestrator.models import AICall, AIReply
from ai_orchestrator.orchestrator import handle_message
from ai_orchestrator.providers.base import Plan
from catalog.loader import load_catalog
from conversations.models import Conversation
from datasource.executors.base import QueryTimeout
from datasource.executors.fake import FakeQueryExecutor, make_result
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta

pytestmark = pytest.mark.django_db

FRESCOR = make_result(("tabela", "ultima_data"), [("adesoes", "2026-09-29"), ("transacoes", "2026-09-29")])
GRAO = make_result(("adesoes", "pacientes"), [(2796, 2790)])
LEITURAS = make_result(("grupo", "pacientes"), [("comprou o produto aderido", 1776), ("comprou outra apresentação", 43)])
FINAL = make_result(("situacao", "pacientes"), [("Aderiu e concluiu a transação", 1819), ("Aderiu e não concluiu", 971)])
PREMISSAS = (
    "Dado até 29/09: outubro ainda não entrou. Concluiu = compra confirmada depois da adesão, de qualquer "
    "apresentação — 43 pacientes compraram outra que não a da adesão."
)


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


@pytest.fixture
def pergunta(django_user_model):
    user = django_user_model.objects.create_user("amanda", password="x")
    conversa = Conversation.objects.create(user=user)
    return Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND,
        content="quais pacientes aderiram ao PBM em setembro e outubro e concluíram a transação?",
        client_message_id="c-1",
    )


def _reconhecimento(*o_que_confere):
    return plano("", intent=Plan.Intent.EXPLORE, investigacao=tuple(
        {"hipotese": h, "sql": "SELECT 1 FROM pbm.fato_pbm_adesoes", "reference_query_id": ""} for h in o_que_confere
    ))


def _final():
    return plano("SELECT 1 FROM pbm.fato_pbm_adesoes", reference_query_id="", premissas=PREMISSAS)


def _responder(mensagem, catalogo, provider, executor):
    return handle_message(mensagem, channel=FakeChannel(), provider=provider, executor=executor, catalog=catalogo)


def test_sem_referencia_reconhece_o_dado_e_depois_escreve_a_consulta_final(pergunta, catalogo):
    provider = ScriptedAIProvider(
        [_reconhecimento("frescor", "grão e chave", "quanto cada leitura muda"), _final()],
        [resposta("Foram 1.819 pacientes que concluíram.")],
    )
    executor = FakeQueryExecutor([FRESCOR, GRAO, LEITURAS, FINAL])

    reply = _responder(pergunta, catalogo, provider, executor)

    assert len(executor.executed) == 4  # três de reconhecimento e a final
    segundo = provider.plan_requests[1]
    assert "frescor" in segundo.reconhecimento and "2026-09-29" in segundo.reconhecimento
    assert "2790" in segundo.reconhecimento and "1776" in segundo.reconhecimento
    assert provider.answer_requests[0].premissas == PREMISSAS
    assert reply.decision == AIReply.Decision.ANSWERED
    assert [c["o_que_confere"] for c in reply.raw_response["reconhecimento"]] == [
        "frescor", "grão e chave", "quanto cada leitura muda"
    ]
    assert reply.calls.filter(stage=AICall.Stage.EXPLORE).count() == 1


def test_reconhecimento_e_uma_rodada_so(pergunta, catalogo):
    """O prompt proíbe reconhecer de novo; se vier, não há terceira chamada
    paga — a resposta é "não sei", com o motivo registrado."""
    provider = ScriptedAIProvider(
        [_reconhecimento("frescor"), _reconhecimento("de novo")],
        [resposta("não deveria redigir")],
    )
    executor = FakeQueryExecutor([FRESCOR])

    reply = _responder(pergunta, catalogo, provider, executor)

    assert len(provider.plan_requests) == 2
    assert len(executor.executed) == 1
    assert reply.decision == AIReply.Decision.UNKNOWN
    assert provider.answer_requests == []


def test_consulta_de_reconhecimento_que_falha_vai_nos_achados(pergunta, catalogo):
    """Falha de uma consulta de reconhecimento não derruba a pergunta: o erro
    vai para quem escreve a consulta final, que o leva em conta."""
    provider = ScriptedAIProvider(
        [_reconhecimento("frescor", "grão e chave"), _final()],
        [resposta("Foram 1.819 pacientes que concluíram.")],
    )
    executor = FakeQueryExecutor([QueryTimeout("a consulta passou de 60000 ms e foi cancelada"), GRAO, FINAL])

    reply = _responder(pergunta, catalogo, provider, executor)

    assert "60000 ms" in provider.plan_requests[1].reconhecimento
    assert reply.decision == AIReply.Decision.ANSWERED


def test_pergunta_com_referencia_nao_reconhece(pergunta, catalogo):
    """O reconhecimento só existe quando o planejador o pede: a pergunta comum
    continua com uma chamada de plano e uma consulta."""
    provider = ScriptedAIProvider([plano()], [resposta("Foram 1.819 pacientes que concluíram.")])
    executor = FakeQueryExecutor([FINAL])

    _responder(pergunta, catalogo, provider, executor)

    assert len(provider.plan_requests) == 1
    assert provider.plan_requests[0].reconhecimento == ""
    assert len(executor.executed) == 1


def test_reconhecimento_que_deu_certo_vira_rascunho_de_referencia(pergunta, catalogo):
    """A próxima pergunta parecida sai direto, sem reconhecimento, se o time
    de BI aprovar o rascunho no documento."""
    from reporting import referencias_do_uso

    provider = ScriptedAIProvider(
        [_reconhecimento("frescor", "grão e chave"), _final()],
        [resposta("Foram 1.819 pacientes que concluíram.")],
    )
    reply = _responder(pergunta, catalogo, provider, FakeQueryExecutor([FRESCOR, GRAO, FINAL]))

    [pendente] = referencias_do_uso.pendentes()
    texto = referencias_do_uso.rascunho(pendente)

    assert pendente.pk == reply.pk
    assert "-- RASCUNHO · quais pacientes aderiram" in texto
    assert "outubro ainda não entrou" in texto
    assert "frescor; grão e chave" in texto


def test_reconhecimento_com_polegar_para_baixo_nao_vira_rascunho(pergunta, catalogo):
    from messaging.models import Avaliacao
    from reporting import referencias_do_uso

    provider = ScriptedAIProvider(
        [_reconhecimento("frescor"), _final()], [resposta("Foram 1.819 pacientes que concluíram.")]
    )
    _responder(pergunta, catalogo, provider, FakeQueryExecutor([FRESCOR, FINAL]))
    resposta_enviada = Message.objects.get(in_reply_to=pergunta)
    Avaliacao.objects.create(message=resposta_enviada, nota=Avaliacao.Nota.ERRADA)

    assert referencias_do_uso.pendentes() == []
