"""Investigação de perguntas de porquê (ADR-0025).

O caso que motivou: "Porque a Ease Labs caiu em Sell Out em jul/26?" voltou
como uma tabela, sem racional. O que estes testes fixam:

1. pergunta de porquê vira hipóteses em rodadas, não uma consulta só;
2. os tetos de custo (rodadas e consultas por rodada) valem sempre;
3. a análise cruza as consultas, e cada número dela está em alguma;
4. a resposta sai em blocos, e bloco que aponta dado errado cai.
"""

import pytest

from ai_orchestrator import canned, progresso
from ai_orchestrator.context import (
    MAX_PASSOS_POR_RODADA,
    MAX_RODADAS,
    e_pergunta_de_porque,
    escolher_secoes_da_investigacao,
)
from ai_orchestrator.models import AICall, AIReply
from ai_orchestrator.providers.base import Plan
from datasource.executors.fake import FakeQueryExecutor, make_result
from datasource.models import QueryRun
from tests.fakes.providers import ScriptedAIProvider, plano, resposta
from tests.unit.test_orchestrator import _pergunta, _responder, catalogo, conversa  # noqa: F401

pytestmark = pytest.mark.django_db

PERGUNTA = "Porque a Ease Labs caiu em Sell Out em jul/26?"
PREMISSA = make_result(("mes", "und", "var_pct"), [("2026-06", 8100.0, None), ("2026-07", 7200.0, -11.1)])
POR_GR = make_result(("gr", "var_und", "var_pct"), [("GR Sul", -700.0, -35.0), ("GR Norte", -40.0, -2.0)])
SETORES = make_result(("gr", "setores_vagos"), [("GR Sul", 3.0), ("GR Norte", 0.0)])


def _passo(hipotese, sql="SELECT und FROM cddd.vendas_consolidado"):
    return {"hipotese": hipotese, "sql": sql, "reference_query_id": "B01"}


def _investiga(*passos, **campos):
    return plano(sql="", intent=Plan.Intent.INVESTIGATE, investigacao=tuple(passos), **campos)


def _conclui():
    return plano(sql="", intent=Plan.Intent.CONCLUDE, reason="os achados já explicam")


def _analise(texto="A queda de 11,1% foi concentrada no GR Sul, que caiu 35%.", blocos=()):
    return resposta(texto, blocos=blocos)


# ------------------------------------------------------------ detecção


@pytest.mark.parametrize("texto", [
    PERGUNTA,
    "Por que o representante X perdeu market share no mês mais recente?",
    "O que explica a queda de PX em agosto?",
    "Qual a causa da ruptura no CD de Recife?",
])
def test_pergunta_de_porque_e_reconhecida(texto):
    assert e_pergunta_de_porque(texto)


@pytest.mark.parametrize("texto", ["Quantas unidades vendemos em julho?", "Qual o share da Ease em agosto?"])
def test_pergunta_de_numero_nao_e_investigacao(texto):
    assert not e_pergunta_de_porque(texto)


def test_investigacao_leva_os_temas_do_roteiro():
    """A queda é medida no sell-out, localizada na força de vendas e
    explicada na prescrição: faltar um tema leva ao documento inteiro."""
    assert set(escolher_secoes_da_investigacao(PERGUNTA)) == {"sell_out", "forca_vendas", "prescricao"}


# -------------------------------------------------------------- rodadas


def test_porque_vira_hipoteses_em_rodadas_e_uma_analise(conversa, catalogo):
    provider = ScriptedAIProvider(
        [_investiga(_passo("a queda se confirma?"), _passo("foi geral ou concentrada?")), _conclui()],
        [_analise()],
    )

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([PREMISSA, POR_GR]))

    assert reply.decision == AIReply.Decision.ANSWERED
    assert [p["hipotese"] for p in reply.raw_response["investigacao"]] == [
        "a queda se confirma?", "foi geral ou concentrada?",
    ]
    assert list(AICall.objects.values_list("stage", flat=True)) == [
        AICall.Stage.PLAN, AICall.Stage.INVESTIGATE, AICall.Stage.ANSWER,
    ]
    # A redação recebeu as duas consultas, não só a última.
    assert len(provider.answer_requests[0].consultas) == 2
    assert QueryRun.objects.count() == 2


def test_rodada_seguinte_le_os_achados(conversa, catalogo):
    provider = ScriptedAIProvider(
        [_investiga(_passo("foi geral ou concentrada?")), _investiga(_passo("setores vagos no GR Sul?")), _conclui()],
        [_analise("O GR Sul teve 3 setores vagos e caiu 35%.")],
    )

    _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
               executor=FakeQueryExecutor([POR_GR, SETORES]))

    segunda = provider.plan_requests[1]
    assert segunda.rodada == 2
    assert "GR Sul" in segunda.achados and "foi geral ou concentrada?" in segunda.achados
    assert "setores vagos no GR Sul?" in provider.plan_requests[2].achados


def test_numero_de_rodadas_tem_teto(conversa, catalogo):
    """O planejador quer sempre aprofundar; o custo não pode depender disso."""
    sempre_mais = [_investiga(_passo(f"hipótese {i}")) for i in range(MAX_RODADAS + 3)]
    provider = ScriptedAIProvider(sempre_mais, [_analise("O GR Sul caiu 35%.")])

    _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
               executor=FakeQueryExecutor([POR_GR] * (MAX_RODADAS + 3)))

    assert len(provider.plan_requests) == MAX_RODADAS
    assert QueryRun.objects.count() == MAX_RODADAS


def test_consultas_por_rodada_tem_teto(conversa, catalogo):
    passos = [_passo(f"hipótese {i}") for i in range(MAX_PASSOS_POR_RODADA + 3)]
    provider = ScriptedAIProvider([_investiga(*passos), _conclui()], [_analise("O GR Sul caiu 35%.")])

    _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
               executor=FakeQueryExecutor([POR_GR] * 10))

    assert QueryRun.objects.count() == MAX_PASSOS_POR_RODADA


def test_consulta_recusada_nao_ganha_correcao_propria_e_vai_nos_achados(conversa, catalogo):
    """Correção por hipótese multiplicaria o custo: o erro vai nos achados e
    o planejador reescreve na rodada seguinte, se importar."""
    provider = ScriptedAIProvider(
        [_investiga(_passo("apaga?", sql="DELETE FROM cddd.pdvs"), _passo("foi concentrada?")), _conclui()],
        [_analise("O GR Sul caiu 35%.")],
    )

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([POR_GR]))

    assert "recusada pelo validador" in provider.plan_requests[1].achados
    assert reply.raw_response["investigacao"][0]["erro"].startswith("recusada")
    assert AICall.objects.filter(stage=AICall.Stage.FIX).count() == 0


def test_investigacao_sem_nenhum_dado_diz_isso(conversa, catalogo):
    vazio = make_result(("gr", "var_und"), [])
    provider = ScriptedAIProvider([_investiga(_passo("foi concentrada?")), _conclui()])

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([vazio]))

    assert reply.reply_text == canned.INVESTIGACAO_SEM_DADO
    assert provider.answer_requests == []


def test_progresso_e_limpo_no_fim(conversa, catalogo):
    mensagem = _pergunta(conversa, PERGUNTA)
    provider = ScriptedAIProvider([_investiga(_passo("foi concentrada?")), _conclui()],
                                  [_analise("O GR Sul caiu 35%.")])

    _responder(mensagem, catalogo, provider=provider, executor=FakeQueryExecutor([POR_GR]))

    assert progresso.ler(mensagem.pk) == ""


# -------------------------------------------------------------- análise


def test_analise_cita_numeros_de_consultas_diferentes(conversa, catalogo):
    """11,1 vem da premissa; 35 e 3 vêm de outras consultas. Todos valem."""
    provider = ScriptedAIProvider(
        [_investiga(_passo("premissa"), _passo("concentrada?"), _passo("setores vagos?")), _conclui()],
        [_analise("Caiu 11,1%, concentrado no GR Sul (35%), que teve 3 setores vagos.")],
    )

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([PREMISSA, POR_GR, SETORES]))

    assert reply.rule == ""
    assert "3 setores vagos" in reply.reply_text


def test_numero_que_nenhuma_consulta_trouxe_e_reescrito(conversa, catalogo):
    provider = ScriptedAIProvider(
        [_investiga(_passo("concentrada?")), _conclui()],
        [_analise("O GR Sul caiu 48%."), _analise("O GR Sul caiu 35%.")],
    )

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([POR_GR]))

    assert provider.answer_requests[1].revision_note
    assert reply.reply_text == "O GR Sul caiu 35%."


def test_analise_reprovada_duas_vezes_mostra_as_evidencias(conversa, catalogo):
    provider = ScriptedAIProvider(
        [_investiga(_passo("foi concentrada?")), _conclui()],
        [_analise("Caiu 48%."), _analise("Caiu 49%.")],
    )

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([POR_GR]))

    assert reply.rule == "analise_sem_narrativa"
    tabelas = [b for b in reply.raw_response["blocos"] if b["tipo"] == "tabela"]
    assert tabelas[0]["titulo"] == "foi concentrada?"
    assert reply.raw_response["dados_blocos"]["0"]["rows"][0][0] == "GR Sul"


# ----------------------------------------------------------------- blocos


def test_blocos_validos_ficam_com_os_dados_das_consultas(conversa, catalogo):
    blocos = (
        {"tipo": "texto", "texto": "A queda foi concentrada no GR Sul."},
        {"tipo": "tabela", "consulta": 1, "colunas": ["gr", "var_pct"]},
        {"tipo": "texto", "texto": "O resto do país ficou estável."},
        {"tipo": "grafico", "consulta": 1, "grafico": {"tipo": "barras", "x": "gr", "series": ["var_und"], "titulo": ""}},
    )
    provider = ScriptedAIProvider(
        [_investiga(_passo("premissa"), _passo("concentrada?")), _conclui()],
        [_analise("A queda foi concentrada no GR Sul. O resto do país ficou estável.", blocos=blocos)],
    )

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([PREMISSA, POR_GR]))

    guardados = reply.raw_response["blocos"]
    assert [b["tipo"] for b in guardados] == ["texto", "tabela", "texto", "grafico"]
    assert guardados[1]["colunas"] == ["gr", "var_pct"]
    assert set(reply.raw_response["dados_blocos"]) == {"1"}


def test_bloco_que_aponta_dado_errado_cai(conversa, catalogo):
    blocos = (
        {"tipo": "texto", "texto": "O GR Sul caiu."},
        {"tipo": "tabela", "consulta": 7, "colunas": []},
        {"tipo": "grafico", "consulta": 0, "grafico": {"tipo": "barras", "x": "nao_existe", "series": ["var_und"]}},
        {"tipo": "tabela", "consulta": 0, "colunas": ["coluna_inventada"]},
    )
    provider = ScriptedAIProvider(
        [_investiga(_passo("concentrada?")), _conclui()], [_analise("O GR Sul caiu.", blocos=blocos)]
    )

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([POR_GR]))

    guardados = reply.raw_response["blocos"]
    # Índice 7 não existe e o gráfico aponta coluna inexistente: caem. A
    # tabela com coluna inventada vira a tabela com todas as colunas.
    assert [b["tipo"] for b in guardados] == ["texto", "tabela"]
    assert guardados[1]["colunas"] == ["gr", "var_und", "var_pct"]


def test_blocos_sem_texto_nenhum_sao_descartados(conversa, catalogo):
    blocos = ({"tipo": "tabela", "consulta": 0, "colunas": []},)
    provider = ScriptedAIProvider(
        [_investiga(_passo("concentrada?")), _conclui()], [_analise("O GR Sul caiu.", blocos=blocos)]
    )

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([POR_GR]))

    assert "blocos" not in reply.raw_response


def test_resposta_comum_tambem_pode_vir_em_blocos(conversa, catalogo):
    """Não é só investigação: texto, tabela e texto quando isso lê melhor."""
    blocos = (
        {"tipo": "texto", "texto": "Foram 47 unidades."},
        {"tipo": "tabela", "consulta": 0, "colunas": []},
    )
    provider = ScriptedAIProvider([plano()], [resposta("Foram 47 unidades.", blocos=blocos)])

    reply = _responder(_pergunta(conversa), catalogo, provider=provider)

    assert [b["tipo"] for b in reply.raw_response["blocos"]] == ["texto", "tabela"]
    assert "0" in reply.raw_response["dados_blocos"]
