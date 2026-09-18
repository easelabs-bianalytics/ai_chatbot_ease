"""Executor somente leitura contra o banco analítico sintético local.

Roda no container `analytics_db` do docker-compose, com o usuário
`bi_readonly` — o mesmo desenho que o RDS terá (D-01). É aqui que se prova
que as camadas 1 e 2 do ADR-0008 funcionam de verdade, e não só no papel.
"""

import os

import pytest

from catalog.loader import load_catalog
from datasource.executors.base import QueryExecutionError, QueryTimeout
from datasource.executors.postgres_readonly import PostgresReadOnlyExecutor
from datasource.sql_guard import validate_sql

DSN_PADRAO = "postgresql://bi_readonly:bi_readonly_dev@localhost:5435/analytics"


@pytest.fixture(scope="module")
def dsn():
    return os.environ.get("TEST_ANALYTICS_DATABASE_URL", DSN_PADRAO)


@pytest.fixture
def executor(dsn):
    return PostgresReadOnlyExecutor(dsn=dsn, statement_timeout_ms=5000)


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


def test_consulta_simples_devolve_colunas_e_linhas(executor):
    resultado = executor.run(
        "SELECT cod_apresentacao, SUM(und) AS unidades "
        "FROM cddd.vendas_consolidado GROUP BY 1 ORDER BY 1"
    )

    assert resultado.columns == ("cod_apresentacao", "unidades")
    # Os três SKUs do banco sintético, com o Extrato (259434) somando
    # 12 + 8 + 20 + 7 = 47 unidades.
    assert resultado.as_dicts() == [
        {"cod_apresentacao": "234194", "unidades": 5.0},
        {"cod_apresentacao": "254655", "unidades": 3.0},
        {"cod_apresentacao": "259434", "unidades": 47.0},
    ]
    assert resultado.truncated is False


def test_valores_voltam_em_tipos_que_cabem_em_json(executor):
    """O resultado vai para o modelo e para a auditoria em JSON: Decimal e
    date não sobreviveriam à serialização."""
    resultado = executor.run(
        "SELECT ano_mes, qtd FROM cddd.vw_sellout_mensal ORDER BY ano_mes LIMIT 1"
    )

    ano_mes, qtd = resultado.rows[0]
    assert ano_mes == "2026-07-01"
    assert isinstance(qtd, float)


def test_escrita_e_recusada_pelo_proprio_banco(executor):
    """Sem passar pelo validador: mesmo que o nosso código falhasse, a
    transação somente leitura e a permissão do usuário barram (ADR-0008,
    camadas 1 e 2)."""
    with pytest.raises(QueryExecutionError) as erro:
        executor.run("INSERT INTO cddd.pdvs (cod_pdv) VALUES (1)")

    assert "read-only" in str(erro.value).lower()


def test_consulta_demorada_e_cancelada_pelo_banco(dsn):
    """Uma consulta pesada no RDS afeta outros sistemas. O tempo máximo é da
    sessão, então vale mesmo para SQL que o validador aprovou."""
    executor = PostgresReadOnlyExecutor(dsn=dsn, statement_timeout_ms=200)

    with pytest.raises(QueryTimeout):
        executor.run("SELECT pg_sleep(3)")


def test_erro_de_coluna_inexistente_volta_legivel(executor):
    """Esta mensagem vai para a IA na correção única (ADR-0014): ela precisa
    dizer qual coluna não existe."""
    with pytest.raises(QueryExecutionError) as erro:
        executor.run("SELECT coluna_que_nao_existe FROM cddd.pdvs")

    assert "coluna_que_nao_existe" in str(erro.value)
    assert "\n" not in str(erro.value)


def test_validador_e_executor_juntos_cortam_e_sinalizam_o_excesso(executor, catalogo):
    """O validador pede uma linha a mais e o executor corta: é assim que a
    resposta sabe dizer que a lista veio incompleta."""
    aprovada = validate_sql(
        "SELECT cod_anomes, und FROM cddd.vendas_consolidado ORDER BY cod_anomes",
        catalogo,
        max_rows=3,
    )

    resultado = executor.run(aprovada.sql, max_rows=3)

    assert resultado.row_count == 3
    assert resultado.truncated is True


def test_coluna_bloqueada_existe_no_banco_mas_nao_passa_pelo_validador(executor, catalogo):
    """Prova que o bloqueio é decisão nossa, e não efeito de a coluna não
    existir: ela está lá, e ainda assim a consulta não roda."""
    existe = executor.run(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'pbm' AND table_name = 'fato_pbm_transacoes' "
        "AND column_name = 'CPF_CONS'"
    )
    assert existe.rows[0][0] == 1

    assert not validate_sql(
        'SELECT "CPF_CONS" FROM pbm.fato_pbm_transacoes', catalogo
    ).approved


def test_dsn_ausente_falha_com_mensagem_clara():
    with pytest.raises(QueryExecutionError) as erro:
        PostgresReadOnlyExecutor(dsn="").run("SELECT 1")

    assert "ANALYTICS_DATABASE_URL" in str(erro.value)


def test_tabela_ou_schema_inexistente_tem_erro_proprio(executor):
    """O documento de referência manda dizer que a informação não está
    disponível, e não trocar por outra tabela. Para isso o orquestrador
    precisa distinguir "não existe" de "consulta errada"."""
    from datasource.executors.base import QueryObjectMissing

    with pytest.raises(QueryObjectMissing):
        executor.run("SELECT mes FROM remuneracao_fv.fato_remuneracao")
