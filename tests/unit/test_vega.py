"""Gráfico em Vega-Lite (ADR-0026).

A IA escreve o desenho; o dado vem do banco. Estes testes fixam as duas
metades: qualquer gráfico que a gramática descreve passa, e nada que busque
dado, navegue para fora ou cite campo que o resultado não tem.
"""

import json

from ai_orchestrator.vega import validar

COLUNAS = ("competencia", "especialidade", "px")
LINHAS = (("2026-01", "NEUROLOGIA", 900), ("2026-02", "PSIQUIATRIA", 700))


def _validar(spec, colunas=COLUNAS, linhas=LINHAS):
    return validar(json.dumps(spec), colunas, linhas, "px por especialidade", "SELECT 1")


def test_dispersao_passa():
    """O pedido que motivou o ADR (2026-09-23): 'um gráfico de dispersão'."""
    spec = {"mark": "point", "encoding": {
        "x": {"field": "competencia", "type": "temporal"},
        "y": {"field": "px", "type": "quantitative"},
    }}
    assert _validar(spec) == spec


def test_camadas_e_transformacao_com_campo_criado_passam():
    spec = {
        "transform": [{"calculate": "datum.px / 1000", "as": "mil_px"}],
        "layer": [
            {"mark": "bar", "encoding": {"x": {"field": "especialidade"}, "y": {"field": "px"}}},
            {"mark": "line", "encoding": {"x": {"field": "especialidade"}, "y": {"field": "mil_px"}}},
        ],
    }
    assert _validar(spec) is not None


def test_dado_colado_na_especificacao_e_removido():
    """O número vem do banco, nunca da IA: `data` sai, e a tela põe o resultado."""
    spec = {"data": {"values": [{"px": 999999}]}, "mark": "bar",
            "encoding": {"x": {"field": "especialidade"}, "y": {"field": "px"}}}

    limpa = _validar(spec)

    assert "data" not in limpa
    assert limpa["mark"] == "bar"


def test_campo_que_o_resultado_nao_tem_e_recusado():
    spec = {"mark": "bar", "encoding": {"x": {"field": "rede"}, "y": {"field": "px"}}}
    assert _validar(spec) is None


def test_endereco_externo_e_recusado():
    """Nada de buscar dado de fora nem abrir link a partir de um valor do banco."""
    for spec in (
        {"mark": "bar", "encoding": {"x": {"field": "px"}}, "title": "veja https://exemplo.com"},
        {"mark": "image", "encoding": {"x": {"field": "px"}, "url": {"field": "especialidade"}}},
        {"mark": "bar", "encoding": {"x": {"field": "px"}, "href": {"value": "javascript:alert(1)"}}},
    ):
        assert _validar(spec) is None


def test_link_e_url_somem_mesmo_sem_texto_perigoso():
    spec = {"mark": "bar", "encoding": {"x": {"field": "especialidade"}, "y": {"field": "px"},
                                        "href": {"field": "especialidade"}}}

    limpa = _validar(spec)

    assert "href" not in limpa["encoding"]


def test_titulo_com_numero_sem_fonte_sai():
    spec = {"mark": "bar", "title": "Crescimento de 37%",
            "encoding": {"x": {"field": "especialidade"}, "y": {"field": "px"}}}

    assert "title" not in _validar(spec)


def test_texto_que_nao_e_especificacao_e_recusado():
    assert validar("isto não é JSON", COLUNAS, LINHAS, "", "") is None
    assert validar(json.dumps({"encoding": {}}), COLUNAS, LINHAS, "", "") is None
    assert validar("x" * 13000, COLUNAS, LINHAS, "", "") is None
