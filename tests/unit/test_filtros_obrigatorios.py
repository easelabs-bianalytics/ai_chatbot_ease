"""Sell In realizado é só Venda e Venda - PBM (Rubens, 2026-10-20).

As próximas cargas da `estoque_redes.fato_sell_in` vão trazer outros tipos
de utilização (devolução, bonificação, remessa). Uma consulta sem o filtro
rodaria sem erro e contaria tudo como venda. O validador recusa.
"""

import pytest

from catalog.loader import load_catalog
from datasource.sql_guard import validate_sql

FILTRO = "\"Utilização\" IN ('Venda', 'Venda - PBM')"


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


def test_consulta_sem_o_filtro_e_recusada(catalogo):
    guard = validate_sql('SELECT SUM("$T") FROM estoque_redes.fato_sell_in', catalogo)

    assert not guard.approved
    assert FILTRO in guard.reason


def test_consulta_com_o_filtro_passa(catalogo):
    assert validate_sql(f'SELECT SUM("$T") FROM estoque_redes.fato_sell_in WHERE {FILTRO}', catalogo).approved


def test_so_um_dos_dois_passa_quando_o_usuario_pede(catalogo):
    sql = "SELECT SUM(\"$T\") FROM estoque_redes.fato_sell_in WHERE \"Utilização\" = 'Venda - PBM'"
    assert validate_sql(sql, catalogo).approved


def test_outro_tipo_de_utilizacao_e_recusado(catalogo):
    sql = "SELECT SUM(\"$T\") FROM estoque_redes.fato_sell_in WHERE \"Utilização\" IN ('Venda', 'Bonificação')"
    assert not validate_sql(sql, catalogo).approved


def test_filtro_dentro_de_or_nao_vale(catalogo):
    """`... OR "Estado" = 'SP'` deixaria passar qualquer utilização de SP."""
    sql = f"SELECT SUM(\"$T\") FROM estoque_redes.fato_sell_in WHERE {FILTRO} OR \"Estado\" = 'SP'"
    assert not validate_sql(sql, catalogo).approved


def test_cada_uso_da_tabela_precisa_do_filtro(catalogo):
    """A SI5 usa a tabela duas vezes: a data de corte também conta."""
    sem_no_corte = (
        "WITH corte AS (SELECT MAX(\"DT EMISSÃO\") AS d FROM estoque_redes.fato_sell_in) "
        f"SELECT SUM(f.\"$T\") FROM estoque_redes.fato_sell_in f CROSS JOIN corte c WHERE f.{FILTRO}"
    )
    assert not validate_sql(sem_no_corte, catalogo).approved

    com_nos_dois = sem_no_corte.replace("FROM estoque_redes.fato_sell_in)",
                                        f"FROM estoque_redes.fato_sell_in WHERE {FILTRO})")
    assert validate_sql(com_nos_dois, catalogo).approved


def test_view_do_sell_in_tambem(catalogo):
    assert not validate_sql("SELECT SUM(valor_total) FROM estoque_redes.vw_dados_sell_in", catalogo).approved
    sql = "SELECT SUM(valor_total) FROM estoque_redes.vw_dados_sell_in WHERE tipo_movimentacao IN ('Venda', 'Venda - PBM')"
    assert validate_sql(sql, catalogo).approved


def test_todas_as_referencias_de_sell_in_passam(catalogo):
    refs = [r for r in catalogo.references if "fato_sell_in" in r.sql or "vw_dados_sell_in" in r.sql]
    assert refs
    for ref in refs:
        guard = validate_sql(ref.sql.replace(":data_ini", "'2026-01-01'"), catalogo)
        assert guard.approved, (ref.id, guard.reason)
