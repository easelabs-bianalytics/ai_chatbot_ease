"""Carregamento do catálogo e das consultas de referência (ADR-0006)."""

import textwrap

import pytest

from catalog.errors import CatalogError
from catalog.loader import build_catalog, load_catalog, parse_reference_queries

CATALOGO_MINIMO = {
    "schemas_permitidos": ["cddd"],
    "limites": {"max_linhas": 10, "timeout_ms": 1000, "linhas_para_o_modelo": 5},
}

REFERENCIAS_MINIMAS = textwrap.dedent(
    """
    ```sql
    -- Q01 · Sell-out mensal
    SELECT qtd FROM cddd.vw_sellout_mensal;
    ```
    """
)


def test_le_o_catalogo_real_do_projeto():
    catalogo = load_catalog()

    assert "cddd" in catalogo.schemas
    assert catalogo.blocked_columns_for("pbm.fato_pbm_transacoes")
    assert catalogo.references


def test_identificador_e_titulo_da_referencia_sao_extraidos():
    consultas = parse_reference_queries(REFERENCIAS_MINIMAS)

    assert consultas[0].id == "Q01"
    assert consultas[0].title == "Sell-out mensal"
    assert consultas[0].sql.startswith("SELECT qtd")


def test_referencia_sem_cabecalho_falha_alto():
    """Sem o "-- Qxx" a resposta não teria como registrar em qual referência
    se baseou, e a métrica de uso das referências (ADR-0014) perderia o
    sentido."""
    with pytest.raises(CatalogError):
        parse_reference_queries("```sql\nSELECT 1;\n```")


def test_referencias_com_id_repetido_falham_alto():
    texto = REFERENCIAS_MINIMAS + REFERENCIAS_MINIMAS

    with pytest.raises(CatalogError):
        parse_reference_queries(texto)


def test_arquivo_sem_nenhuma_consulta_falha_alto():
    with pytest.raises(CatalogError):
        parse_reference_queries("# só texto, nenhuma consulta")


def test_catalogo_sem_schemas_falha_alto():
    """Catálogo vazio recusaria toda consulta, e o sintoma apareceria como
    "a IA não consegue responder nada" em vez de erro de configuração."""
    with pytest.raises(CatalogError):
        build_catalog({**CATALOGO_MINIMO, "schemas_permitidos": []}, REFERENCIAS_MINIMAS, "x")


def test_catalogo_sem_limites_falha_alto():
    dados = {"schemas_permitidos": ["cddd"]}

    with pytest.raises(CatalogError):
        build_catalog(dados, REFERENCIAS_MINIMAS, "x")


def test_coluna_bloqueada_sem_schema_falha_alto():
    """"pdvs" sem schema casaria com tabela nenhuma, e a coluna seguiria
    acessível achando que estava protegida."""
    dados = {
        **CATALOGO_MINIMO,
        "colunas_bloqueadas": {"pdvs": {"colunas": ["cpf"]}},
    }

    with pytest.raises(CatalogError):
        build_catalog(dados, REFERENCIAS_MINIMAS, "x")


def test_hash_muda_quando_o_conhecimento_muda(tmp_path):
    """O hash vai em cada resposta e no relatório de validação: é ele que
    denuncia um relatório gerado com outro catálogo."""
    catalogo_yaml = tmp_path / "catalog.yaml"
    referencias = tmp_path / "refs.md"
    catalogo_yaml.write_text(
        "schemas_permitidos: [cddd]\nlimites: {max_linhas: 10, timeout_ms: 1000, linhas_para_o_modelo: 5}\n",
        encoding="utf-8",
    )
    referencias.write_text(REFERENCIAS_MINIMAS, encoding="utf-8")
    antes = load_catalog(catalogo_yaml, referencias).hash

    referencias.write_text(
        REFERENCIAS_MINIMAS.replace("Sell-out mensal", "Sell-out mensal por SKU"),
        encoding="utf-8",
    )
    depois = load_catalog(catalogo_yaml, referencias).hash

    assert antes != depois
