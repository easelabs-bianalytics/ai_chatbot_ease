"""Coluna de percentual sai com o símbolo, nos quatro lugares.

O pedido do Rubens em 2026-09-22: "Share Ease Varejo YTD 2026 = 9,23" na
tabela não diz de quê. O número é o mesmo; o que faltava era a unidade — e
ela só existe no nome da coluna, porque o banco devolve `9.23` tanto para
share quanto para unidades.

A regra mora em `datasource/colunas.py` e vale para a tabela, o texto, o
rótulo do gráfico e a célula da planilha devolvida. A tela tem a cópia dela
em `app.js`; se um dia divergirem, a mesma resposta mostra `9,23%` num lugar
e `9,23` no outro.
"""

import io

from openpyxl import Workbook, load_workbook

from ai_orchestrator.orchestrator import formatar_valor
from attachments.planilha import PedidoDePreenchimento, preencher
from datasource.colunas import e_percentual


def test_reconhece_as_colunas_de_percentual():
    assert e_percentual("share_pct")
    assert e_percentual("var_pct_ache_vs_ease")
    assert e_percentual("share_ease_varejo_ytd_2026")
    assert e_percentual("participacao_mercado")
    assert e_percentual("retencao_90d_pct")


def test_nao_confunde_coluna_comum_com_percentual():
    """`unidades` e `valor` não podem ganhar um "%" que ninguém pediu."""
    assert not e_percentual("unidades")
    assert not e_percentual("valor_total")
    assert not e_percentual("rede")
    assert not e_percentual("competencia")
    # "pct" precisa ser a palavra, não um pedaço de outra.
    assert not e_percentual("expectativa")


def test_valor_de_percentual_sai_com_simbolo():
    assert formatar_valor(9.23, "share_pct") == "9,23%"
    assert formatar_valor(-78.61, "var_pct_ache_vs_ease") == "-78,61%"
    assert formatar_valor(22, "share_pct") == "22%"
    # Sem a coluna, o comportamento é o de antes.
    assert formatar_valor(9.23) == "9,23"
    assert formatar_valor(3851, "unidades") == "3.851"


def _planilha(coluna: str = "Share") -> bytes:
    livro = Workbook()
    livro.active.append(["Rede", coluna])
    livro.active.append(["Panvel", None])
    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()


def test_celula_de_percentual_ganha_formato_no_excel():
    """O valor na célula continua sendo 9,23 — soma e gráfico do arquivo
    seguem funcionando. Quem mostra o símbolo é o formato."""
    pedido = PedidoDePreenchimento(
        coluna_chave="Rede",
        chave_no_resultado="rede",
        colunas=(("Share", "share_pct"),),
    )

    saida = preencher("redes.xlsx", _planilha(), pedido, ("rede", "share_pct"), [("Panvel", 9.23)])

    celula = load_workbook(io.BytesIO(saida.dados)).active["B2"]
    assert celula.value == 9.23
    assert "%" in celula.number_format


def test_celula_comum_nao_ganha_formato_de_percentual():
    pedido = PedidoDePreenchimento(
        coluna_chave="Rede",
        chave_no_resultado="rede",
        colunas=(("Unidades", "unidades"),),
    )

    saida = preencher(
        "redes.xlsx", _planilha("Unidades"), pedido, ("rede", "unidades"), [("Panvel", 12.0)]
    )

    assert "%" not in load_workbook(io.BytesIO(saida.dados)).active["B2"].number_format
