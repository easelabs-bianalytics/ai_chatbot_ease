"""Snapshot do schema real (catalog/snapshot.py e comando catalog_snapshot)."""

import pytest
from django.core.management import CommandError, call_command

from catalog.loader import load_catalog
from catalog.snapshot import render_snapshot


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


RELACOES = {
    "pbm.fato_pbm_transacoes": {
        "tipo": "tabela",
        "colunas": [("STATUS_TRN", "text"), ("CPF_CONS", "text"), ("TELEFONE", "text")],
    },
    "cddd.vendas_consolidado": {
        "tipo": "view",
        "colunas": [("cod_anomes", "date"), ("und", "numeric")],
    },
    "pbm.fato_pbm_transacoes_stg": {"tipo": "tabela", "colunas": [("EAN", "text")]},
}


def test_colunas_de_dado_pessoal_nao_aparecem_no_snapshot(catalogo):
    """A IA nem fica sabendo que CPF e telefone existem. É mais forte do que
    proibir o uso: não dá para pedir o que não se conhece."""
    texto, resumo = render_snapshot(RELACOES, catalogo, gerado_em="2026-09-16 10:00")

    assert "CPF_CONS" not in texto
    assert "TELEFONE" not in texto
    assert resumo["colunas_omitidas"] == 2


def test_tabela_bloqueada_nao_aparece_no_snapshot(catalogo):
    """As tabelas de staging do PBM existem no banco, mas têm o dado bruto do
    consumidor: a IA nem fica sabendo delas."""
    texto, resumo = render_snapshot(RELACOES, catalogo)

    assert "fato_pbm_transacoes_stg" not in texto
    assert resumo["tabelas_omitidas"] == 1


def test_coluna_maiuscula_sai_entre_aspas(catalogo):
    """É assim que a IA precisa escrevê-la no SQL; sem aspas o Postgres
    procura "status_trn" e a consulta quebra."""
    texto, _ = render_snapshot(RELACOES, catalogo)

    assert '"STATUS_TRN" text' in texto
    assert "cod_anomes date" in texto


def test_relacoes_saem_agrupadas_por_schema(catalogo):
    texto, resumo = render_snapshot(RELACOES, catalogo)

    assert texto.index("## cddd") < texto.index("## pbm")
    assert "`cddd.vendas_consolidado` (view)" in texto
    assert resumo["schemas"] == 2
    assert resumo["relacoes"] == 2


def test_snapshot_sem_banco_configurado_falha_alto(tmp_path):
    """Sem banco, a fábrica devolve o executor fake. Se o comando aceitasse,
    o arquivo sairia com dado de mentira e a IA passaria a acreditar nele."""
    with pytest.raises(CommandError, match="não configurado"):
        call_command("catalog_snapshot", saida=str(tmp_path / "snap.md"))

    assert not (tmp_path / "snap.md").exists()


def test_snapshot_entra_no_hash_do_catalogo(tmp_path):
    """Regerar o snapshot muda o que a IA sabe do banco, então precisa mudar
    o hash gravado em cada resposta — senão um relatório de validação antigo
    pareceria atual."""
    snapshot = tmp_path / "schema.md"
    snapshot.write_text("# versão 1", encoding="utf-8")
    antes = load_catalog(snapshot_path=snapshot)

    snapshot.write_text("# versão 2", encoding="utf-8")
    depois = load_catalog(snapshot_path=snapshot)

    assert antes.hash != depois.hash
    assert depois.schema_text == "# versão 2"


def test_catalogo_sem_snapshot_ainda_carrega(tmp_path):
    catalogo = load_catalog(snapshot_path=tmp_path / "nao_existe.md")

    assert catalogo.schema_text == ""
