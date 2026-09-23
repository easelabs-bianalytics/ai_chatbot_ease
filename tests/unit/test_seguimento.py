"""Seguimento que pede mudança: o que o planejador entendeu e o que não fez.

Incidente (conversa 15, 2026-09-23): depois do comparativo de setembro contra
agosto, o usuário pediu "considere Extras, Mercado Público, Saúde Suplementar
e Voucher também". A IA repetiu a consulta anterior, devolveu o mesmo número
e escreveu que tinha considerado o Voucher. Nada obrigava o planejador a
dizer o que tinha entendido do pedido, e a redação não sabia o que ficou de
fora. Estes testes seguram o encanamento desses dois campos — do modelo até a
redação e o registro de auditoria.
"""

import pytest

from ai_orchestrator.models import AIReply
from ai_orchestrator.orchestrator import handle_message
from ai_orchestrator.providers.base import AnswerRequest, PlanRequest
from ai_orchestrator.providers.openai_provider import (
    OpenAIProvider,
    PlanoEstruturado,
    RespostaEstruturada,
)
from catalog.loader import load_catalog
from conversations.models import Conversation
from datasource.executors.fake import FakeQueryExecutor, make_result
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta

ENTENDIMENTO = (
    "Vendas Ease de 1 a 20/09/2026 contra 1 a 20/08/2026, agora somando Extras, "
    "Mercado Público e Saúde Suplementar nos dois períodos, com o Voucher descontado"
)
NAO_ATENDIDO = "meta por representante não existe no banco"


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


class _Uso:
    def __init__(self):
        self.input_tokens = 1000
        self.output_tokens = 100
        self.input_tokens_details = None
        self.output_tokens_details = None


class _Resposta:
    def __init__(self, conteudo):
        self.output_parsed = conteudo
        self.usage = _Uso()


class _Cliente:
    def __init__(self, respostas):
        self._respostas = list(respostas)
        self.chamadas = []
        self.responses = self

    def parse(self, **kwargs):
        self.chamadas.append(kwargs)
        return self._respostas.pop(0)


def _provider(catalogo, respostas):
    return OpenAIProvider(catalog=catalogo, client=_Cliente(respostas), model="gpt-5.6-terra",
                          answer_model="gpt-5.6-luna")


def test_entendimento_vem_antes_do_sql_no_schema():
    """O modelo escreve na ordem do schema. Dizer o que entendeu antes de
    escrever a consulta é o que faz o seguimento mudar o SQL; se o campo for
    parar depois do `sql`, vira justificativa do que já foi escrito."""
    campos = list(PlanoEstruturado.model_fields)
    assert campos.index("entendimento") < campos.index("sql")
    assert "pedido_nao_atendido" in campos


def test_plano_devolve_entendimento_e_o_que_nao_atendeu(catalogo):
    conteudo = PlanoEstruturado(
        intent="answer_with_data", sql="SELECT 1 FROM cddd.vw_sell_out", reference_query_id="B43",
        entendimento=f"  {ENTENDIMENTO}  ", pedido_nao_atendido=NAO_ATENDIDO,
    )
    provider = _provider(catalogo, [_Resposta(conteudo)])

    saida = provider.plan(PlanRequest(question="Considere Extras, Mercado Público e Saúde Suplementar também"))

    assert saida.entendimento == ENTENDIMENTO
    assert saida.pedido_nao_atendido == NAO_ATENDIDO


def test_redacao_recebe_o_que_nao_foi_atendido_com_a_ordem_de_dizer(catalogo):
    """Sem a instrução junto, a redação descrevia a consulta como se tivesse
    feito o pedido: "a comparação considera CDD e Voucher"."""
    provider = _provider(catalogo, [_Resposta(RespostaEstruturada(reply="Foram 4.306 unidades."))])

    provider.answer(AnswerRequest(
        question="Considere a meta também", sql="SELECT 1", columns=("unidades",), rows=((4306,),),
        truncated=False, entendimento=ENTENDIMENTO, pedido_nao_atendido=NAO_ATENDIDO,
    ))

    entrada = provider._client.chamadas[0]["input"]
    assert ENTENDIMENTO in entrada
    assert NAO_ATENDIDO in entrada
    assert "Nunca escreva que considerou algo" in entrada


def test_redacao_sem_pendencia_nao_ganha_secao_vazia(catalogo):
    provider = _provider(catalogo, [_Resposta(RespostaEstruturada(reply="Foram 47 unidades."))])

    provider.answer(AnswerRequest(question="q", sql="SELECT 1", columns=("u",), rows=((47,),), truncated=False))

    assert "NÃO atendeu" not in provider._client.chamadas[0]["input"]


@pytest.mark.django_db
def test_orquestrador_leva_os_campos_a_redacao_e_ao_registro(django_user_model, catalogo):
    """O caminho inteiro: o plano diz o que entendeu e o que ficou de fora, a
    redação recebe os dois, e o registro guarda os dois para quem audita no
    Admin por que a resposta saiu como saiu."""
    usuario = django_user_model.objects.create_user("paulo", password="x")
    conversa = Conversation.objects.create(user=usuario)
    mensagem = Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND, client_message_id="c-15",
        content="Considere Extras, Mercado Público, Saúde Suplementar e Voucher também",
        status=Message.Status.RECEIVED,
    )
    provider = ScriptedAIProvider(
        [plano("SELECT periodo, total FROM cddd.vw_sell_out", reference_query_id="B43",
               entendimento=ENTENDIMENTO, pedido_nao_atendido=NAO_ATENDIDO)],
        [resposta("Somando todas as fontes, foram 4306 unidades contra 5004.")],
    )
    executor = FakeQueryExecutor([make_result(("periodo", "total"), [("atual", 4306), ("anterior", 5004)])])

    reply = handle_message(mensagem, channel=FakeChannel(), provider=provider, executor=executor, catalog=catalogo)

    assert reply.decision == AIReply.Decision.ANSWERED
    pedido = provider.answer_requests[0]
    assert pedido.entendimento == ENTENDIMENTO
    assert pedido.pedido_nao_atendido == NAO_ATENDIDO
    assert reply.raw_response["entendimento"] == ENTENDIMENTO
    assert reply.raw_response["pedido_nao_atendido"] == NAO_ATENDIDO


# ------------------------------------------------ seguimento, entregas e autocrítica


def test_plano_devolve_seguimento_e_entregas_sem_as_que_vieram_sem_sql(catalogo):
    from ai_orchestrator.providers.openai_provider import ConsultaEstruturada

    conteudo = PlanoEstruturado(
        intent="answer_with_data", seguimento=" MUDA_O_DADO ",
        consultas=[ConsultaEstruturada(titulo="Evolução", sql="SELECT 1", reference_query_id="A01"),
                   ConsultaEstruturada(titulo="Ranking", sql="  ")],
    )
    provider = _provider(catalogo, [_Resposta(conteudo)])

    saida = provider.plan(PlanRequest(question="Evolução e ranking das especialidades"))

    assert saida.seguimento == "muda_o_dado"
    assert saida.consultas == ({"titulo": "Evolução", "sql": "SELECT 1", "reference_query_id": "A01"},)


def test_seguimento_desconhecido_vira_vazio(catalogo):
    provider = _provider(catalogo, [_Resposta(PlanoEstruturado(intent="answer_with_data", sql="SELECT 1",
                                                               seguimento="talvez"))])

    assert provider.plan(PlanRequest(question="vendas de setembro")).seguimento == ""


def test_segunda_chance_leva_a_autocritica_ao_planejador(catalogo):
    provider = _provider(catalogo, [_Resposta(PlanoEstruturado(intent="answer_with_data", sql="SELECT 1"))])

    provider.plan(PlanRequest(question="Considere Extras também", autocritica_note="mesmos números da anterior"))

    chamada = provider._client.chamadas[0]
    texto = "".join(b["text"] for m in chamada["input"] for b in m["content"]) if not isinstance(
        chamada["input"], str) else chamada["input"]
    assert "# Autocrítica do seguimento" in texto and "mesmos números da anterior" in texto
    # Com autocrítica não há atalho para o modelo barato: é pergunta de dado.
    assert chamada["model"] == "gpt-5.6-terra"


def test_redacao_de_entregas_pede_resposta_a_cada_uma(catalogo):
    provider = _provider(catalogo, [_Resposta(RespostaEstruturada(reply="Neurologia lidera."))])

    provider.answer(AnswerRequest(
        question="evolução e ranking", sql="", columns=(), rows=(), truncated=False, entregas=True,
        entendimento=ENTENDIMENTO,
        consultas=({"titulo": "Ranking", "hipotese": "Ranking", "sql": "SELECT 1", "columns": ("a",),
                    "rows": ((1,),), "total_rows": 1},),
    ))

    entrada = provider._client.chamadas[0]["input"]
    assert "# Várias entregas" in entrada and "## Consulta 0: Ranking" in entrada
    assert "# Investigação" not in entrada
    assert ENTENDIMENTO in entrada


def test_historico_leva_o_resumo_em_linhas(catalogo):
    from ai_orchestrator.providers.base import HistoryMessage

    # Pergunta curta passa antes pelo modelo barato e sobe: duas chamadas.
    provider = _provider(catalogo, [_Resposta(PlanoEstruturado(intent="answer_with_data", sql="SELECT 1"))] * 2)

    provider.plan(PlanRequest(question="e em julho?", history=(
        HistoryMessage(direction="out", text="Foram 47.", fonte="- consulta (base B01): 1 linhas\n  sql: SELECT 1"),
    )))

    chamada = provider._client.chamadas[0]
    texto = "".join(b["text"] for m in chamada["input"] for b in m["content"])
    assert "  [o que sustentou esta resposta]\n  - consulta (base B01): 1 linhas\n    sql: SELECT 1" in texto
