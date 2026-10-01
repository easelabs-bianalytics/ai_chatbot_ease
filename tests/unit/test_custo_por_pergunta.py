"""Custo de uma pergunta sob controle (2026-10-01).

A pergunta "painel da Força de Vendas × Área Médica" custou US$ 0,30: o
planejador pediu a seção do Marketing ("PRECISO DA SEÇÃO: marketing") e o
sistema mandou o documento inteiro, 81 mil tokens, para trazer uma seção de
5 mil. O que estes testes fixam:

1. o tema pedido é lido do motivo do plano;
2. a segunda chamada leva esse tema completo, não o documento inteiro;
3. a correção da consulta continua com o mesmo recorte;
4. passado o teto por pergunta, as chamadas opcionais param.
"""

import pytest

from ai_orchestrator.context import montar_contexto_do_plano, secoes_do_pedido
from ai_orchestrator.models import AIReply
from ai_orchestrator.providers.base import AIUsage, Plan
from datasource.executors.fake import FakeQueryExecutor, make_result
from tests.fakes.providers import ScriptedAIProvider, plano, resposta
from tests.unit.test_orchestrator import _pergunta, _responder, catalogo, conversa  # noqa: F401

pytestmark = pytest.mark.django_db

RESULTADO = make_result(("representante", "medicos"), [("ANA", 3)])


@pytest.mark.parametrize("motivo, esperado", [
    ("PRECISO DA SEÇÃO: marketing. O resumo indica a referência M04...", ("marketing",)),
    ("PRECISO DA SEÇÃO: Sell Out CDD — os filtros padrão", ("sell_out",)),
    ("PRECISO DA SEÇÃO: Força de Vendas e Área Médica", ("forca_vendas", "marketing")),
    ("PRECISO DA SEÇÃO: não sei qual", ()),
])
def test_tema_pedido_e_lido_do_motivo(motivo, esperado):
    assert secoes_do_pedido(motivo) == esperado


def test_tema_pedido_vai_completo_e_sem_o_documento_inteiro(catalogo):
    pergunta = "Pegue os médicos do painel da Força de Vendas e veja quais estão na Área Médica"
    normal = montar_contexto_do_plano(catalogo, pergunta)
    pedido = montar_contexto_do_plano(catalogo, pergunta, secoes_pedidas=("marketing",))
    inteiro = montar_contexto_do_plano(catalogo, pergunta, completo=True)

    assert pedido.secoes[0] == "marketing" and not pedido.completo
    assert "-- M04 ·" in pedido.texto
    assert "Tema relacionado (resumo)" not in pedido.texto
    # A ordem de grandeza é o que importa: o documento inteiro custava ~4x.
    assert pedido.tokens_estimados < inteiro.tokens_estimados / 2
    assert normal.tokens_estimados <= pedido.tokens_estimados


def _pede_secao(secao="marketing"):
    return plano(sql="", intent=Plan.Intent.UNKNOWN, reason=f"PRECISO DA SEÇÃO: {secao}. O resumo não traz a M04.")


def test_pedido_de_secao_reenvia_so_ela(conversa, catalogo):
    provider = ScriptedAIProvider([_pede_secao(), plano()], [resposta("são 3 médicos")])

    reply = _responder(_pergunta(conversa, "quais médicos do painel estão na Área Médica?"), catalogo,
                       provider=provider, executor=FakeQueryExecutor([RESULTADO]))

    segunda = provider.plan_requests[1]
    assert segunda.secoes_pedidas == ("marketing",)
    assert segunda.full_context is False
    assert reply.decision == AIReply.Decision.ANSWERED


def test_pedido_sem_tema_reconhecivel_ainda_leva_o_documento(conversa, catalogo):
    provider = ScriptedAIProvider([_pede_secao("não sei"), plano()], [resposta("são 3 médicos")])

    _responder(_pergunta(conversa, "quais médicos do painel estão na Área Médica?"), catalogo,
               provider=provider, executor=FakeQueryExecutor([RESULTADO]))

    assert provider.plan_requests[1].full_context is True


def test_correcao_usa_o_mesmo_recorte(conversa, catalogo):
    """Consulta recusada depois do pedido de seção: a correção não pode
    voltar ao recorte que não bastou."""
    com_secao = plano(usage=AIUsage(model="stub", request={"secoes_pedidas": ["marketing"]}))
    errado = plano(sql="DELETE FROM marketing.email_contatos",
                   usage=AIUsage(model="stub", request={"secoes_pedidas": ["marketing"]}))
    provider = ScriptedAIProvider([_pede_secao(), errado, com_secao], [resposta("são 3 médicos")])

    _responder(_pergunta(conversa, "quais médicos do painel estão na Área Médica?"), catalogo,
               provider=provider, executor=FakeQueryExecutor([RESULTADO]))

    assert provider.plan_requests[2].secoes_pedidas == ("marketing",)
    assert provider.plan_requests[2].error_note


def _caro(**campos):
    return plano(usage=AIUsage(model="stub", cost_estimate=0.2, tokens_input=1, tokens_output=1), **campos)


def test_teto_por_pergunta_para_a_investigacao(conversa, catalogo, monkeypatch):
    monkeypatch.setenv("AI_MAX_COST_PER_QUESTION", "0.15")
    passo = {"hipotese": "a queda se confirma?", "sql": "SELECT und FROM cddd.vendas_consolidado",
             "reference_query_id": "B01"}
    caro = _caro(sql="", intent=Plan.Intent.INVESTIGATE, investigacao=(passo,))
    provider = ScriptedAIProvider([caro], [resposta("caiu 11,1%")])

    reply = _responder(_pergunta(conversa, "Porque a Ease Labs caiu em Sell Out em jul/26?"), catalogo,
                       provider=provider, executor=FakeQueryExecutor([make_result(("var_pct",), [(-11.1,)])]))

    # Só o plano da rodada 1: a rodada 2 não foi pedida.
    assert len(provider.plan_requests) == 1
    assert reply.raw_response["teto_por_pergunta"] == ["rodada 2 da investigação"]


def test_teto_por_pergunta_pula_a_verificacao_do_vazio(conversa, catalogo, monkeypatch):
    monkeypatch.setenv("AI_MAX_COST_PER_QUESTION", "0.15")
    vazio = make_result(("und",), [])
    provider = ScriptedAIProvider([_caro()], [])

    reply = _responder(_pergunta(conversa), catalogo, provider=provider, executor=FakeQueryExecutor([vazio]))

    assert len(provider.plan_requests) == 1
    assert reply.decision == AIReply.Decision.EMPTY_RESULT
    assert "verificação do resultado vazio" in reply.raw_response["teto_por_pergunta"]
