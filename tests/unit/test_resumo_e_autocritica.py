"""Histórico estruturado e autocrítica do seguimento.

Incidente (conversa 15, 2026-09-23): o planejador via só os primeiros 1.200
caracteres do SQL da resposta anterior — a B17 tem uns 2.600 — e, ao pedido
"considere Extras, MP e SS também", repetiu a consulta e devolveu o mesmo
4.306 × 4.716. Estes testes seguram as duas defesas genéricas: o resumo em
campos (com o SQL inteiro da última resposta) e a segunda chance quando um
seguimento que muda o dado devolve os mesmos números.
"""

import pytest

from ai_orchestrator import autocritica, progresso, resumo
from ai_orchestrator.models import AICall, AIReply
from datasource.executors.fake import FakeQueryExecutor, make_result
from tests.fakes.providers import ScriptedAIProvider, plano, resposta
from tests.unit.test_orchestrator import _pergunta, _responder, catalogo, conversa  # noqa: F401

pytestmark = pytest.mark.django_db

# Uma consulta longa, como a B17: o período do mês anterior só aparece no fim.
SQL_LONGO = (
    "WITH atual AS (SELECT SUM(und) AS und FROM cddd.vendas_consolidado WHERE data >= DATE '2026-09-01' "
    "AND data < DATE '2026-09-21' AND canal <> 'hospitalar'), "
    + " ".join(f"c{n} AS (SELECT {n} AS x)," for n in range(60))
    + " anterior AS (SELECT SUM(und) AS und FROM cddd.vendas_consolidado WHERE data >= DATE '2026-08-01' "
    "AND data < DATE '2026-08-21') SELECT a.und AS atual, p.und AS anterior FROM atual a, anterior p"
)
ANTES = make_result(("atual", "anterior"), [(4306, 4716)])
DEPOIS = make_result(("atual", "anterior"), [(4306, 5004)])


def _primeira_resposta(conversa, catalogo, sql=SQL_LONGO, resultado=ANTES):
    provider = ScriptedAIProvider(
        [plano(sql, reference_query_id="B17", entendimento="Vendas 1–20/09 contra 1–20/08, só CDD")],
        [resposta("Foram 4.306 unidades contra 4.716.")],
    )
    return _responder(_pergunta(conversa, "Vendas deste mês contra o mesmo período do anterior"), catalogo,
                      provider=provider, executor=FakeQueryExecutor([resultado]))


# ---------------------------------------------------------------- resumo


def test_resumo_traz_entendimento_filtros_datas_e_numeros(conversa, catalogo):
    reply = _primeira_resposta(conversa, catalogo)

    texto = resumo.resumir(reply)

    assert "entendido: Vendas 1–20/09 contra 1–20/08" in texto
    assert "base B17" in texto
    assert "cddd.vendas_consolidado" in texto
    assert "2026-08-01" in texto and "2026-09-21" in texto     # os dois períodos
    assert '"anterior": 4716' in texto                          # os números que voltaram
    assert "sql:" not in texto


def test_ultima_resposta_leva_o_sql_inteiro_ao_planejador(conversa, catalogo):
    """O corte em 1.200 caracteres escondia o mês anterior da B17."""
    assert len(SQL_LONGO) > 1200
    _primeira_resposta(conversa, catalogo)
    provider = ScriptedAIProvider([plano()], [resposta()])

    _responder(_pergunta(conversa, "Considere Extras também", client_id="c-2"), catalogo, provider=provider)

    fonte = provider.plan_requests[0].history[-1].fonte
    assert " ".join(SQL_LONGO.split()) in fonte


def test_so_a_ultima_resposta_com_dado_leva_o_sql(conversa, catalogo):
    _primeira_resposta(conversa, catalogo)
    provider = ScriptedAIProvider([plano("SELECT und FROM cddd.vendas_consolidado WHERE uf = 'CE'")],
                                  [resposta()])
    _responder(_pergunta(conversa, "e no Ceará?", client_id="c-2"), catalogo, provider=provider)
    provider = ScriptedAIProvider([plano()], [resposta()])

    _responder(_pergunta(conversa, "e em julho?", client_id="c-3"), catalogo, provider=provider)

    fontes = [m.fonte for m in provider.plan_requests[0].history if m.direction == "out"]
    assert "sql:" not in fontes[0]
    assert "sql:" in fontes[1] and "uf = 'CE'" in fontes[1]


# ---------------------------------------------------------------- mesmo resultado


def test_mesmos_numeros_com_outro_nome_de_coluna_sao_o_mesmo_resultado():
    """Trocar `vendas` por `vendas_total` e devolver os mesmos valores é o
    erro que a conferência quer pegar."""
    anterior = autocritica.Anterior(colunas=("vendas",), linhas=((4306, 4716.0),), row_count=1, sql="")

    assert autocritica.mesmo_resultado(make_result(("vendas_total", "x"), [(4306.0, 4716)]), anterior)
    assert not autocritica.mesmo_resultado(make_result(("a", "b"), [(4306, 5004)]), anterior)
    assert not autocritica.mesmo_resultado(make_result(("a", "b"), [(4306, 4716), (1, 2)]), anterior)


def test_resultado_sem_numero_nao_e_comparado():
    anterior = autocritica.Anterior(colunas=("nome",), linhas=(("Ana",),), row_count=1, sql="")

    assert not autocritica.mesmo_resultado(make_result(("nome",), [("Ana",)]), anterior)


# ---------------------------------------------------------------- segunda chance


def _seguimento(conversa, catalogo, planos, resultados, respostas=None, texto="Considere Extras e MP também"):
    provider = ScriptedAIProvider(planos, respostas or [resposta("Somando tudo, 4.306 contra 5.004.")])
    reply = _responder(_pergunta(conversa, texto, client_id="c-2"), catalogo, provider=provider,
                       executor=FakeQueryExecutor(resultados))
    return reply, provider


def test_seguimento_que_repete_os_numeros_ganha_segunda_chance(conversa, catalogo):
    _primeira_resposta(conversa, catalogo)

    reply, provider = _seguimento(
        conversa, catalogo,
        [plano(SQL_LONGO, seguimento="muda_o_dado", entendimento="agora com Extras e MP"),
         plano("SELECT und FROM cddd.vendas_consolidado", seguimento="muda_o_dado")],
        [ANTES, DEPOIS],
    )

    assert "mesmos números da resposta anterior" in provider.plan_requests[1].autocritica_note
    assert "agora com Extras e MP" in provider.plan_requests[1].autocritica_note
    assert provider.answer_requests[0].rows == ((4306, 5004),)
    assert reply.raw_response["autocritica"] == {
        "motivo": "mesmos números da resposta anterior", "refeita": True, "mudou": True,
    }
    assert reply.calls.filter(stage=AICall.Stage.SELF_CHECK).count() == 1
    # A consulta que vale é a última: é dela que a tela e o histórico leem.
    assert reply.query_runs.order_by("-attempt").first().sql == "SELECT und FROM cddd.vendas_consolidado"


def test_segunda_chance_que_mantem_a_consulta_avisa_a_redacao(conversa, catalogo):
    """O planejador pode concluir que a mudança não altera o número (a fonte
    está zerada). Aí a redação precisa dizer isso, não apresentar o mesmo
    número como novo."""
    _primeira_resposta(conversa, catalogo)

    reply, provider = _seguimento(
        conversa, catalogo,
        [plano(SQL_LONGO, seguimento="muda_o_dado"), plano(SQL_LONGO, seguimento="muda_o_dado")],
        [ANTES],
        respostas=[resposta("Continua 4.306 contra 4.716: Extras e MP estão zerados.")],
    )

    assert provider.answer_requests[0].pedido_nao_atendido == autocritica.NAO_MUDOU
    assert reply.raw_response["autocritica"]["refeita"] is False


def test_segunda_chance_com_motivo_do_planejador_usa_o_motivo(conversa, catalogo):
    _primeira_resposta(conversa, catalogo)

    _, provider = _seguimento(
        conversa, catalogo,
        [plano(SQL_LONGO, seguimento="muda_o_dado"),
         plano(SQL_LONGO, seguimento="muda_o_dado", pedido_nao_atendido="Extras de setembro sem carga")],
        [ANTES],
        respostas=[resposta("Continua 4.306 contra 4.716.")],
    )

    assert provider.answer_requests[0].pedido_nao_atendido == "Extras de setembro sem carga"


@pytest.mark.parametrize("seguimento", ["so_apresentacao", "repete", ""])
def test_sem_mudanca_de_dado_o_mesmo_resultado_e_o_esperado(conversa, catalogo, seguimento):
    """"Muda para barras" e "refaça" devolvem os mesmos números de propósito:
    nenhuma segunda chance, nenhum centavo a mais."""
    _primeira_resposta(conversa, catalogo)

    reply, provider = _seguimento(
        conversa, catalogo, [plano(SQL_LONGO, seguimento=seguimento)], [ANTES],
        respostas=[resposta("Foram 4.306 contra 4.716.")], texto="mostra em barras",
    )

    assert len(provider.plan_requests) == 1
    assert "autocritica" not in reply.raw_response


def test_segunda_chance_que_falha_fica_com_a_primeira_consulta(conversa, catalogo):
    _primeira_resposta(conversa, catalogo)

    reply, provider = _seguimento(
        conversa, catalogo,
        [plano(SQL_LONGO, seguimento="muda_o_dado"),
         plano("SELECT und FROM cddd.vendas_consolidado WHERE 1 = 0", seguimento="muda_o_dado")],
        [ANTES, make_result(("atual", "anterior"), [])],
        respostas=[resposta("Foram 4.306 contra 4.716.")],
    )

    assert reply.decision == AIReply.Decision.ANSWERED
    assert provider.answer_requests[0].rows == ((4306, 4716),)
    assert provider.answer_requests[0].pedido_nao_atendido == autocritica.NAO_MUDOU
    assert reply.query_runs.order_by("-attempt").first().sql == SQL_LONGO


# ---------------------------------------------------------------- etapas na tela


def test_tela_ve_o_entendimento_e_a_etapa_enquanto_a_resposta_nao_chega(conversa, catalogo):
    """Hoje a tela mostrava "Pensando…" por até 170 s. A pessoa passa a ver
    "Entendi: …" e em que etapa está, a tempo de parar um pedido mal lido."""
    mensagem = _pergunta(conversa, "vendas de setembro")
    vistos = []
    provider = ScriptedAIProvider([plano(entendimento="Vendas Ease de set/2026, todas as fontes")],
                                  [resposta()])
    provider.ao_responder = lambda _: vistos.append(progresso.ler_tudo(mensagem.pk))

    _responder(mensagem, catalogo, provider=provider)

    assert vistos == [{
        "texto": "Escrevendo a resposta", "etapa": "escrevendo",
        "entendimento": "Vendas Ease de set/2026, todas as fontes",
    }]
