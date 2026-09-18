"""Planilha Excel do resultado (ADR-0020).

A planilha vai para fora da ferramenta: alguém abre no Excel, filtra e
manda por e-mail. O que se testa aqui é o que estragaria esse uso — CNPJ
virando notação científica, data como texto, e a planilha sem dizer de onde
veio.
"""

import datetime
import io

import pytest
from openpyxl import load_workbook

from datasource.export import montar_planilha

INFO = {
    "pergunta": "quantas unidades a Pague Menos dispensou por mês em 2026?",
    "gerada_em": "18/09/2026 10:45",
    "linhas": 2,
    "observacao": "Lista completa.",
    "referencia": "B04",
    "sql": "SELECT mes, und FROM cddd.vendas_consolidado",
}


def _abrir(colunas, linhas, info=None):
    return load_workbook(io.BytesIO(montar_planilha(colunas, linhas, info or INFO)))


def test_cabecalho_humanizado_e_primeira_linha_congelada():
    """Quem abre a planilha não lê SQL: `total_und` vira "Total und"."""
    aba = _abrir(("mes", "total_und"), [("2026-08", 777)])["Dados"]

    assert [c.value for c in aba[1]] == ["Mes", "Total und"]
    assert aba.freeze_panes == "A2"
    assert aba.auto_filter.ref == "A1:B2"


def test_cnpj_e_ean_vao_como_texto():
    """Como número, o CNPJ perde o zero à esquerda e vira 1,23457E+13 —
    o suficiente para a planilha não servir para cruzar nada."""
    aba = _abrir(("cnpj_pdv", "cod_ean"), [("01234567000199", 7891234567890)])["Dados"]

    assert aba["A2"].value == "01234567000199"
    assert aba["B2"].value == "7891234567890"
    assert isinstance(aba["B2"].value, str)


def test_data_iso_vira_data_de_verdade_no_formato_brasileiro():
    aba = _abrir(("dia", "und"), [("2026-08-15", 12)])["Dados"]

    # O Excel guarda data como número de série: na releitura volta datetime,
    # e quem manda na aparência é o formato da célula.
    assert aba["A2"].value == datetime.datetime(2026, 8, 15)
    assert aba["A2"].number_format == "dd/mm/yyyy"
    assert aba["B2"].number_format == "#,##0"


def test_numero_com_decimal_mantem_duas_casas():
    aba = _abrir(("share_pct",), [(12.34,)])["Dados"]

    assert aba["A2"].number_format == "#,##0.00"


@pytest.mark.parametrize("valor,esperado", [(True, "Sim"), (False, "Não"), (None, None)])
def test_booleano_e_vazio_saem_legiveis(valor, esperado):
    aba = _abrir(("visitado",), [(valor,)])["Dados"]

    assert aba["A2"].value == esperado


def test_aba_de_informacoes_diz_de_onde_veio():
    """Sem isso a planilha vira um arquivo solto: ninguém lembra qual
    pergunta ela respondia nem com que consulta."""
    livro = _abrir(("mes", "und"), [("2026-08", 777)])
    aba = livro["Informações"]
    textos = [f"{aba.cell(row=n, column=1).value}: {aba.cell(row=n, column=2).value}" for n in range(4, 10)]

    assert livro.sheetnames == ["Dados", "Informações"]
    assert any("Pague Menos" in t for t in textos)
    assert any("B04" in t for t in textos)
    assert any("SELECT mes, und" in t for t in textos)


def test_resultado_cortado_avisa_na_planilha():
    info = {**INFO, "observacao": "Lista cortada em 50.000 linhas; refine o filtro."}
    aba = _abrir(("mes",), [("2026-08",)], info)["Informações"]

    assert any("cortada" in str(aba.cell(row=n, column=2).value or "") for n in range(4, 10))


def test_resultado_sem_linhas_gera_planilha_valida():
    """Consulta que não retornou nada não pode virar erro no download."""
    aba = _abrir(("mes", "und"), [])["Dados"]

    assert aba.max_row == 1
