"""Snapshot gerado do banco analítico sintético, pelo usuário de leitura."""

import os

from django.core.management import call_command

DSN_PADRAO = "postgresql://bi_readonly:bi_readonly_dev@localhost:5435/analytics"


def test_snapshot_do_banco_traz_colunas_e_omite_as_bloqueadas(monkeypatch, tmp_path):
    """Caminho completo: permissão real do banco, views e tabelas, bloqueio do
    catálogo e aspas nas colunas maiúsculas do PBM."""
    monkeypatch.setenv(
        "ANALYTICS_DATABASE_URL", os.environ.get("TEST_ANALYTICS_DATABASE_URL", DSN_PADRAO)
    )
    destino = tmp_path / "schema.md"

    call_command("catalog_snapshot", saida=str(destino), stdout=open(os.devnull, "w", encoding="utf-8"))

    texto = destino.read_text(encoding="utf-8")
    assert "`cddd.vendas_consolidado`" in texto
    assert '"STATUS_TRN" text' in texto
    assert "CPF_CONS" not in texto
