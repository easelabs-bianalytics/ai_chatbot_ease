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


# --- polimento do desenho (conversa 22, 2026-09-24) --------------------------

MENSAL = ("mes", "unidades", "tendencia_unidades")
MESES = (("2026-01-01", 262.0, 288.2), ("2026-02-01", 267.0, 289.0), ("2026-03-01", 217.0, 289.9))


def _barras_com_tendencia(tamanho=None):
    barra = {"type": "bar", "size": tamanho} if tamanho else "bar"
    return {"layer": [
        {"mark": barra, "encoding": {"x": {"field": "mes", "type": "temporal"},
                                     "y": {"field": "unidades", "type": "quantitative"}}},
        {"mark": {"type": "line", "point": True},
         "encoding": {"x": {"field": "mes", "type": "temporal"},
                      "y": {"field": "tendencia_unidades", "type": "quantitative"}}},
    ]}


def test_barras_mensais_em_eixo_de_data_viram_faixas_do_mes():
    """Barra em eixo de data saía fina como linha; com `size` fixo, a de
    janeiro invadia o eixo Y."""
    spec = _validar(_barras_com_tendencia(tamanho=42), MENSAL, MESES)

    for camada in spec["layer"]:
        assert camada["encoding"]["x"]["type"] == "ordinal"
        assert camada["encoding"]["x"]["timeUnit"] == "yearmonth"
    assert "size" not in spec["layer"][0]["mark"]


def test_barras_diarias_continuam_temporais():
    diarias = (("2026-01-01", 1.0, 1.0), ("2026-01-02", 2.0, 2.0))

    spec = _validar(_barras_com_tendencia(), MENSAL, diarias)

    assert spec["layer"][0]["encoding"]["x"]["type"] == "temporal"


def test_linha_de_tendencia_sobre_barras_ganha_cor_e_tracejado():
    spec = _validar(_barras_com_tendencia(), MENSAL, MESES)

    linha = spec["layer"][1]["mark"]
    assert linha["color"] != "" and linha["strokeDash"] == [6, 4]
    assert linha["point"]["color"] == linha["color"]


COMPOSICAO = ("componente", "valor", "rotulo")
FATIAS = (("CDD", 291.0, "CDD: 291"), ("Extras", 92.0, "Extras: 92"), ("Mercado Público", 0.0, "MP: 0"))


def test_pizza_sem_fatia_zerada_e_com_rotulo_no_meio_da_fatia():
    """Os rótulos das fatias zeradas empilhavam no topo, ilegíveis, e sem
    `stack` cada rótulo caía no começo da fatia, em cima da vizinha."""
    spec = _validar({"layer": [
        {"mark": {"type": "arc", "outerRadius": 110},
         "encoding": {"theta": {"field": "valor", "type": "quantitative"},
                      "color": {"field": "componente", "type": "nominal"}}},
        {"mark": {"type": "text", "radius": 135},
         "encoding": {"theta": {"field": "valor", "type": "quantitative"},
                      "text": {"field": "rotulo", "type": "nominal"}, "color": {"value": "black"}}},
    ]}, COMPOSICAO, FATIAS)

    assert {"filter": 'datum["valor"] > 0'} in spec["transform"]
    for camada in spec["layer"]:
        assert camada["encoding"]["theta"]["stack"] is True
    texto = spec["layer"][1]
    assert "color" not in texto["encoding"]
    assert any("__total_das_fatias" in json.dumps(t) for t in texto["transform"])
