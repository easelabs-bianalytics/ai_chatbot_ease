"""Falhas da conversa "perguntas tricky - testes" de produção (2026-09-21).

As que eram de raciocínio foram para o prompt (planner_v2, seção 7.1). Estas
são as que eram do sistema, e cada teste reproduz a falha real.
"""

from datetime import date

import pytest

from ai_orchestrator import canned
from ai_orchestrator.grounding import check_grounding
from ai_orchestrator.models import AIReply
from ai_orchestrator.orchestrator import AMOSTRA_DA_LISTA_LONGA
from ai_orchestrator.providers.base import AIOutputTruncated
from ai_orchestrator.providers.openai_provider import _saida_cortada
from ai_orchestrator.providers.retrying import RetryingAIProvider
from datasource.executors.fake import FakeQueryExecutor, make_result
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta
from tests.unit.test_orchestrator import _pergunta, _responder, catalogo, conversa  # noqa: F401

pytestmark = pytest.mark.django_db

RUPTURA = make_result(
    ("rede", "cd", "produto", "dde_base"),
    [("RAIA", f"CD {i}", "EXTRATO", 3.0) for i in range(50)],
)


# ---------------------------------------------- "2026" depois de "de qual ano?"


def test_resposta_curta_a_um_pedido_de_detalhe_vai_ao_planejador(conversa, catalogo):
    """O Jarvis perguntou "De qual ano é agosto?", a pessoa respondeu
    "2026" e ouviu "Não consegui entender a pergunta"."""
    primeira = _pergunta(conversa, "Quantas prescrições tivemos em agosto?", "c-1")
    _responder(primeira, catalogo, provider=ScriptedAIProvider([plano(sql="", intent="clarify",
               clarification_question="De qual ano é agosto?")]))
    provider = ScriptedAIProvider([plano()], [resposta("foram 47 unidades")])

    reply = _responder(_pergunta(conversa, "2026", "c-2"), catalogo, provider=provider)

    assert reply.rule != "mensagem_sem_pergunta"
    assert provider.plan_requests[0].question == "2026"


def test_numero_solto_sem_pedido_de_detalhe_continua_recusado(conversa, catalogo):
    reply = _responder(_pergunta(conversa, "2026"), catalogo, provider=ScriptedAIProvider())

    assert reply.rule == "mensagem_sem_pergunta"
    assert reply.reply_text == canned.MENSAGEM_SEM_PERGUNTA


# ------------------------------------------------- resposta cortada no meio


def test_erro_de_json_cortado_e_reconhecido():
    """A mensagem real do SDK, da pergunta da ruptura."""
    erro = Exception(
        "1 validation error for RespostaEstruturada\n  Invalid JSON: EOF while parsing a string at "
        "line 1 column 3875 [type=json_invalid, input_value='{\"reply\":\"**Há 78 regis...'"
    )

    assert _saida_cortada(erro)
    assert not _saida_cortada(Exception("timeout"))


def test_saida_cortada_nao_e_repetida():
    """Em produção a mesma chamada foi feita três vezes, pagando três vezes
    pelo mesmo corte."""
    tentativas = []

    class Corta(ScriptedAIProvider):
        def answer(self, request):
            tentativas.append(1)
            raise AIOutputTruncated("cortada")

    with pytest.raises(AIOutputTruncated):
        RetryingAIProvider(Corta(), dormir=lambda _: None).answer(None)

    assert len(tentativas) == 1


def test_resposta_cortada_vira_tabela_e_nao_problema_tecnico(conversa, catalogo):
    provider = ScriptedAIProvider([plano()], [AIOutputTruncated("cortada")])

    reply = _responder(_pergunta(conversa, "Quais CDs estão em ruptura?"), catalogo,
                       provider=provider, executor=FakeQueryExecutor([RUPTURA]))

    assert reply.decision == AIReply.Decision.ANSWERED
    assert reply.rule == "resposta_sem_narrativa"
    assert reply.reply_text.startswith("rede | cd | produto | dde_base")
    assert Message.objects.get(pk=reply.message_id).status != Message.Status.FAILED


# ------------------------------------------------------ checagem de números

ESTOQUE = (("RAIA", "CD GUARULHOS - SP", "2026-08-27", 172.0, 100.0),)
COLUNAS_DO_ESTOQUE = ("rede", "cd", "data_recebimento", "extrato", "isolado_30ml")


def test_data_de_hoje_pode_ser_citada():
    """A resposta do estoque da Raia disse que a carga não é de hoje (21) e
    foi reprovada por isso."""
    hoje = date.today()
    texto = f"O estoque é da carga de 27/08/2026, não de hoje ({hoje:%d/%m/%Y})."

    assert check_grounding(texto, COLUNAS_DO_ESTOQUE, ESTOQUE, "estoque da Raia hoje?", "").ok


def test_dose_no_nome_da_coluna_pode_ser_citada():
    texto = "O CD de Guarulhos tem 100 unidades do Isolado 30 mL."

    assert check_grounding(texto, COLUNAS_DO_ESTOQUE, ESTOQUE, "estoque da Raia?", "").ok


def test_numero_solto_em_apelido_de_coluna_nao_vale():
    """Senão bastaria o modelo escrever `AS total_4500` para ancorar 4500."""
    texto = "O total é 4500."

    assert not check_grounding(texto, ("total_4500",), ((1.0,),), "total?", "").ok


# ------------------------------------- lista longa não é escrita pelo modelo
# Generalização da falha da ruptura: qualquer resultado com muitas linhas.
# Antes o modelo recebia 50 linhas e era mandado copiá-las; agora recebe uma
# amostra e aponta a tabela, que a tela desenha com os dados do banco.


def test_lista_longa_vai_ao_modelo_como_amostra(conversa, catalogo):
    provider = ScriptedAIProvider([plano()], [resposta("São 50 CDs em ruptura.")])

    _responder(_pergunta(conversa, "Quais CDs estão em ruptura?"), catalogo,
               provider=provider, executor=FakeQueryExecutor([RUPTURA]))

    pedido = provider.answer_requests[0]
    assert pedido.tabela_em_bloco is True
    assert len(pedido.rows) == AMOSTRA_DA_LISTA_LONGA
    assert pedido.total_rows == 50


def test_lista_curta_continua_indo_inteira(conversa, catalogo):
    curta = make_result(("cd", "dde"), [(f"CD {i}", 3.0) for i in range(4)])
    provider = ScriptedAIProvider([plano()], [resposta("São 4 CDs.")])

    _responder(_pergunta(conversa, "Quais CDs estão em ruptura?"), catalogo,
               provider=provider, executor=FakeQueryExecutor([curta]))

    pedido = provider.answer_requests[0]
    assert pedido.tabela_em_bloco is False
    assert len(pedido.rows) == 4


def test_tabela_da_lista_longa_aparece_mesmo_se_o_modelo_nao_apontar(conversa, catalogo):
    """A instrução pode ser ignorada; a pessoa não pode ficar sem a lista."""
    provider = ScriptedAIProvider([plano()], [resposta("São 50 CDs em ruptura.")])

    reply = _responder(_pergunta(conversa, "Quais CDs estão em ruptura?"), catalogo,
                       provider=provider, executor=FakeQueryExecutor([RUPTURA]))

    blocos = reply.raw_response["blocos"]
    assert [b["tipo"] for b in blocos] == ["texto", "tabela"]
    assert blocos[1]["colunas"] == ["rede", "cd", "produto", "dde_base"]
    assert len(reply.raw_response["dados_blocos"]["0"]["rows"]) == 50


def test_tabela_apontada_pelo_modelo_e_respeitada(conversa, catalogo):
    blocos = (
        {"tipo": "texto", "texto": "São 50 CDs em ruptura."},
        {"tipo": "tabela", "consulta": 0, "colunas": ["cd", "dde_base"]},
    )
    provider = ScriptedAIProvider([plano()], [resposta("São 50 CDs em ruptura.", blocos=blocos)])

    reply = _responder(_pergunta(conversa, "Quais CDs estão em ruptura?"), catalogo,
                       provider=provider, executor=FakeQueryExecutor([RUPTURA]))

    guardados = reply.raw_response["blocos"]
    assert len(guardados) == 2
    assert guardados[1]["colunas"] == ["cd", "dde_base"]


# ------------------------------------------------------------- projeções
# O documento de referência passou a permitir projeções (2026-09-22). Em
# projeção de Sell Out ou Sell In da Ease, a orientação sobre o dashboard de
# Forecast de Reposição é acrescentada pelo sistema, não pelo modelo — assim
# ela nunca depende de o modelo lembrar, e não custa token.


def test_projecao_de_sell_out_traz_a_ressalva_do_dashboard(conversa, catalogo):
    provider = ScriptedAIProvider(
        [plano(ressalva_forecast=True)], [resposta("A projeção para outubro é de 47 unidades.")]
    )

    reply = _responder(_pergunta(conversa, "Qual a projeção de sell out para outubro?"),
                       catalogo, provider=provider)

    assert reply.reply_text.endswith(canned.RESSALVA_DE_FORECAST)
    assert reply.raw_response["ressalva_forecast"] is True


def test_projecao_de_px_nao_fala_do_dashboard(conversa, catalogo):
    provider = ScriptedAIProvider([plano()], [resposta("A projeção de PX é de 47 prescrições.")])

    reply = _responder(_pergunta(conversa, "Qual a projeção de PX para outubro?"),
                       catalogo, provider=provider)

    assert "Forecast de Reposição" not in reply.reply_text
