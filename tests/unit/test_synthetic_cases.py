"""Avaliação dos casos de validação, com IA e banco programados.

O relatório da Fase 7 decide se a IA vai para produção. Se o avaliador
aprovar o que devia reprovar, ninguém percebe até um número errado chegar a
um gerente — por isso cada status tem teste aqui.
"""

import decimal

import pytest

from catalog.loader import load_catalog
from datasource.executors.base import QueryObjectMissing
from datasource.executors.fake import FakeQueryExecutor, make_result
from reporting.cases import CaseSuite, RegraDeNegocio, ValidationCase, sql_gabarito
from reporting.comparison import comparar
from reporting.synthetic import (
    APROVADO,
    BLOQUEADOR,
    REPROVADO,
    REVISAO,
    avaliar_caso,
    render_report,
)
from ai_orchestrator.providers.base import Plan
from tests.fakes.providers import ScriptedAIProvider, plano, resposta

RESULTADO = make_result(("cidade", "uf", "representante"), [("CURITIBA", "PR", "CARLOS PEREIRA")])


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


def _caso(**campos):
    base = dict(
        id="E07-teste",
        grupo="referencia",
        pergunta="Curitiba é território de quem?",
        esperado=("answer_with_data",),
        referencia="E07",
        parametros={"cidade": "CURITIBA", "uf": "PR"},
    )
    return ValidationCase(**{**base, **campos})


def _suite(caso, regras=()):
    return CaseSuite(hoje="2026-09-16", regras=tuple(regras), casos=(caso,))


# --- comparação ------------------------------------------------------------


def test_comparacao_ignora_nome_e_ordem_das_colunas():
    gabarito = make_result(("mes", "unidades"), [("2026-08-01", 10), ("2026-07-01", 20)])
    da_ia = make_result(("total_und", "anomes"), [(20.0, "2026-07-01"), (10.0, "2026-08-01")])

    assert comparar(gabarito, da_ia).igual


def test_comparacao_aceita_coluna_a_mais_na_resposta_da_ia():
    gabarito = make_result(("share",), [(12.5,)])
    da_ia = make_result(("faturamento", "share"), [(1000, decimal.Decimal("12.50"))])

    assert comparar(gabarito, da_ia).igual


def test_numero_em_texto_compara_com_numero():
    gabarito = make_result(("anomes",), [("202608",)])
    da_ia = make_result(("anomes",), [(202608,)])

    assert comparar(gabarito, da_ia).igual


def test_valor_diferente_reprova_e_diz_a_coluna():
    gabarito = make_result(("unidades",), [(10,)])
    da_ia = make_result(("unidades",), [(11,)])

    comparacao = comparar(gabarito, da_ia)

    assert not comparacao.igual
    assert "unidades" in comparacao.motivo


def test_quantidade_de_linhas_diferente_reprova():
    gabarito = make_result(("x",), [(1,), (2,)])
    da_ia = make_result(("x",), [(1,)])

    assert not comparar(gabarito, da_ia).igual


def test_resultado_cortado_nao_e_dado_como_igual():
    """Duas listas cortadas em 500 linhas podem coincidir e esconder que o
    total é outro."""
    gabarito = make_result(("x",), [(1,)], truncated=True)

    assert not comparar(gabarito, gabarito).igual


# --- avaliação -------------------------------------------------------------


@pytest.mark.django_db
def test_resposta_certa_com_o_resultado_do_gabarito_e_aprovada(catalogo):
    caso = _caso()
    sql = sql_gabarito(caso, catalogo)
    provider = ScriptedAIProvider([plano(sql=sql, reference_query_id="E07")], [resposta("É do CARLOS PEREIRA.")])
    executor = FakeQueryExecutor([RESULTADO, RESULTADO, RESULTADO])

    resultado = avaliar_caso(caso, _suite(caso), catalogo, provider, executor)

    assert resultado.status == APROVADO, resultado.motivos
    assert resultado.referencia_usada == "E07"
    # pipeline, gabarito e a consulta da IA de novo, com o resultado inteiro
    assert len(executor.executed) == 3


@pytest.mark.django_db
def test_resultado_diferente_do_gabarito_reprova(catalogo):
    caso = _caso()
    sql = sql_gabarito(caso, catalogo)
    outro = make_result(("cidade", "uf", "representante"), [("CURITIBA", "PR", "OUTRA PESSOA")])
    provider = ScriptedAIProvider([plano(sql=sql)], [resposta("É da OUTRA PESSOA.")])
    executor = FakeQueryExecutor([outro, RESULTADO, outro])

    resultado = avaliar_caso(caso, _suite(caso), catalogo, provider, executor)

    assert resultado.status == REPROVADO
    assert any("representante" in m for m in resultado.motivos)


@pytest.mark.django_db
def test_regra_do_documento_descumprida_reprova_mesmo_com_resultado_igual(catalogo):
    """Num período em que não houve venda hospitalar, esquecer o filtro dá o
    mesmo número — e erra no mês seguinte."""
    caso = _caso()
    regra = RegraDeNegocio(
        nome="varejo exclui hospitalar",
        referencias=frozenset({"E07"}),
        sql_deve_conter=(("desc_canal<>'hospitalar'",),),
    )
    sql = sql_gabarito(caso, catalogo)
    provider = ScriptedAIProvider([plano(sql=sql)], [resposta("É do CARLOS PEREIRA.")])
    executor = FakeQueryExecutor([RESULTADO, RESULTADO, RESULTADO])

    resultado = avaliar_caso(caso, _suite(caso, [regra]), catalogo, provider, executor)

    assert resultado.status == REPROVADO
    assert any("varejo exclui hospitalar" in m for m in resultado.motivos)


@pytest.mark.django_db
def test_consultar_quando_devia_perguntar_reprova(catalogo):
    caso = _caso(esperado=("clarify",), grupo="esclarecimento")
    provider = ScriptedAIProvider(
        [plano(sql=sql_gabarito(_caso(), catalogo))], [resposta("É do CARLOS PEREIRA.")]
    )

    resultado = avaliar_caso(caso, _suite(caso), catalogo, provider, FakeQueryExecutor([RESULTADO]))

    assert resultado.status == REPROVADO
    assert "esperado clarify" in resultado.motivos[0]


@pytest.mark.django_db
def test_responder_com_dado_a_pedido_de_seguranca_e_bloqueador(catalogo):
    caso = _caso(grupo="seguranca", esperado=("out_of_scope", "unknown"), referencia="")
    provider = ScriptedAIProvider(
        [plano(sql=sql_gabarito(_caso(), catalogo))], [resposta("É do CARLOS PEREIRA.")]
    )

    resultado = avaliar_caso(caso, _suite(caso), catalogo, provider, FakeQueryExecutor([RESULTADO]))

    assert resultado.status == BLOQUEADOR


@pytest.mark.django_db
def test_tabela_inexistente_conta_como_indisponivel(catalogo):
    """Metas: o documento manda dizer que não está disponível, e o pipeline
    faz isso quando o banco responde que a tabela não existe."""
    caso = _caso(id="B05-teste", referencia="B05", esperado=("indisponivel",), grupo="indisponivel", parametros={})
    provider = ScriptedAIProvider(
        [plano(sql="SELECT r.mes, r.fat_alvo_bonus FROM remuneracao_fv.fato_remuneracao r")]
    )
    executor = FakeQueryExecutor([QueryObjectMissing("relation remuneracao_fv.fato_remuneracao does not exist")])

    resultado = avaliar_caso(caso, _suite(caso), catalogo, provider, executor)

    assert resultado.status == APROVADO, resultado.motivos
    assert resultado.obtido == "indisponivel"


@pytest.mark.django_db
def test_nao_sei_tambem_serve_quando_o_dado_esta_indisponivel(catalogo):
    caso = _caso(id="B05-teste", referencia="B05", esperado=("indisponivel",), grupo="indisponivel")
    provider = ScriptedAIProvider([plano(intent=Plan.Intent.UNKNOWN, sql="", reason="metas não estão no banco")])

    resultado = avaliar_caso(caso, _suite(caso), catalogo, provider, FakeQueryExecutor())

    assert resultado.status == APROVADO


@pytest.mark.django_db
def test_caso_com_mais_de_uma_resposta_certa_vai_para_revisao(catalogo):
    caso = _caso(comparar_resultado=False)
    provider = ScriptedAIProvider(
        [plano(sql=sql_gabarito(caso, catalogo))], [resposta("É do CARLOS PEREIRA.")]
    )

    resultado = avaliar_caso(caso, _suite(caso), catalogo, provider, FakeQueryExecutor([RESULTADO]))

    assert resultado.status == REVISAO


@pytest.mark.django_db
def test_resposta_que_nao_menciona_o_esperado_vai_para_revisao(catalogo):
    caso = _caso(grupo="fora_de_escopo", esperado=("out_of_scope",), referencia="", resposta_deve_conter=("Forecast",))
    provider = ScriptedAIProvider([plano(intent=Plan.Intent.OUT_OF_SCOPE, sql="", reason="projeção")])

    resultado = avaliar_caso(caso, _suite(caso), catalogo, provider, FakeQueryExecutor())

    assert resultado.status == REVISAO
    assert any("Forecast" in m for m in resultado.motivos)


@pytest.mark.django_db
def test_perguntas_anteriores_entram_no_historico(catalogo):
    caso = _caso(antes=("Qual o território de Curitiba?",), pergunta="E de Londrina?")
    provider = ScriptedAIProvider(
        [plano(intent=Plan.Intent.CLARIFY, sql="", clarification_question="Qual UF?"),
         plano(intent=Plan.Intent.CLARIFY, sql="", clarification_question="Qual UF?")]
    )

    avaliar_caso(caso, _suite(caso), catalogo, provider, FakeQueryExecutor())

    segunda = provider.plan_requests[1]
    assert [m.text for m in segunda.history] == ["Qual o território de Curitiba?", "Qual UF?"]


@pytest.mark.django_db
def test_relatorio_traz_totais_e_detalha_o_que_nao_passou(catalogo):
    caso = _caso(esperado=("clarify",), grupo="esclarecimento", nota="precisa perguntar a UF")
    provider = ScriptedAIProvider(
        [plano(sql=sql_gabarito(_caso(), catalogo))], [resposta("É do CARLOS PEREIRA.")]
    )
    resultado = avaliar_caso(caso, _suite(caso), catalogo, provider, FakeQueryExecutor([RESULTADO]))

    texto = render_report([resultado], catalogo, "modelo-x")

    assert "modelo-x" in texto
    assert "| 0 | 1 | 0 | 0 |" in texto
    assert "precisa perguntar a UF" in texto
    assert "```sql" in texto


def test_comparacao_pode_olhar_so_as_colunas_que_respondem_a_pergunta():
    """A B01 abre os componentes do Sell Out; quem perguntou o total não
    precisa deles, e exigi-los reprovaria a IA por trazer menos coluna."""
    gabarito = make_result(("mes", "cdd", "extras", "total"), [("2026-08-01", 10, 2, 12)])
    da_ia = make_result(("mes", "unidades"), [("2026-08-01", 12)])

    assert not comparar(gabarito, da_ia).igual
    assert comparar(gabarito, da_ia, ("mes", "total")).igual
