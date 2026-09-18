"""Validador de SQL (ADR-0008, camada 3).

Com SQL livre, é esta função que decide o que chega ao banco de negócio.
Cada caso aqui é uma forma conhecida de uma consulta gerada por modelo sair
do combinado.
"""

import pytest

from catalog.loader import load_catalog
from datasource.sql_guard import validate_sql


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


def test_consulta_de_leitura_e_aprovada(catalogo):
    resultado = validate_sql(
        "SELECT ano_mes, qtd FROM cddd.vw_sellout_mensal", catalogo
    )

    assert resultado.approved
    assert "cddd.vw_sellout_mensal" in resultado.sql


@pytest.mark.parametrize(
    "sql, trecho_do_motivo",
    [
        ("DELETE FROM cddd.pdvs", "apenas SELECT"),
        ("UPDATE cddd.pdvs SET uf = 'SP'", "apenas SELECT"),
        ("DROP TABLE cddd.pdvs", "apenas SELECT"),
        ("CREATE TABLE cddd.x (i int)", "apenas SELECT"),
        ("TRUNCATE cddd.pdvs", "apenas SELECT"),
        ("SET statement_timeout = 0", "apenas SELECT"),
        ("COPY cddd.pdvs TO '/tmp/x'", "apenas SELECT"),
    ],
)
def test_escrita_e_comando_de_sessao_sao_recusados(catalogo, sql, trecho_do_motivo):
    resultado = validate_sql(sql, catalogo)

    assert not resultado.approved
    assert trecho_do_motivo in resultado.reason


def test_escrita_escondida_dentro_de_cte_e_recusada(catalogo):
    """A consulta começa com WITH e termina em SELECT: quem olhasse só o
    início, ou casasse string, deixaria passar. Por isso a validação percorre
    a árvore inteira."""
    resultado = validate_sql(
        "WITH x AS (DELETE FROM cddd.pdvs RETURNING 1) SELECT * FROM x", catalogo
    )

    assert not resultado.approved
    assert "DELETE" in resultado.reason


def test_dois_comandos_na_mesma_consulta_sao_recusados(catalogo):
    """O clássico do SQL injection: o segundo comando é o que faz o estrago."""
    resultado = validate_sql("SELECT 1; DROP TABLE cddd.pdvs", catalogo)

    assert not resultado.approved
    assert "um único SELECT" in resultado.reason


@pytest.mark.parametrize("schema", ["pg_catalog", "information_schema"])
def test_catalogo_do_sistema_e_recusado(catalogo, schema):
    """Ler o catálogo do sistema é como a IA descobriria tabelas fora do
    combinado — e usuários, permissões e definições de função junto."""
    resultado = validate_sql(f"SELECT * FROM {schema}.tables", catalogo)

    assert not resultado.approved
    assert "sistema" in resultado.reason


def test_schema_fora_do_catalogo_e_recusado(catalogo):
    resultado = validate_sql("SELECT * FROM financeiro.folha", catalogo)

    assert not resultado.approved
    assert "não está liberado" in resultado.reason


def test_tabela_sem_schema_e_recusada(catalogo):
    """Sem schema não dá para saber se a tabela é permitida."""
    resultado = validate_sql("SELECT cod_pdv FROM pdvs", catalogo)

    assert not resultado.approved
    assert "sem schema" in resultado.reason


def test_cte_declarada_na_propria_consulta_nao_precisa_de_schema(catalogo):
    resultado = validate_sql(
        "WITH base AS (SELECT und FROM cddd.vendas_consolidado) "
        "SELECT SUM(und) AS total FROM base",
        catalogo,
    )

    assert resultado.approved


def test_tabela_de_staging_e_recusada(catalogo):
    """As tabelas _stg do PBM guardam o dado bruto do consumidor. A tabela
    tratada tem o mesmo conteúdo para análise, e o motivo da recusa diz qual
    usar, para a IA trocar na correção."""
    resultado = validate_sql('SELECT "EAN" FROM pbm.fato_pbm_transacoes_stg', catalogo)

    assert not resultado.approved
    assert "pbm.fato_pbm_transacoes" in resultado.reason


def test_dado_do_consumidor_na_tabela_de_adesoes_e_recusado(catalogo):
    """A tabela de adesões entrou com o documento novo e tem data de
    nascimento, CPF e contatos do paciente."""
    resultado = validate_sql('SELECT "DATA_NASC" FROM pbm.fato_pbm_adesoes', catalogo)

    assert not resultado.approved


def test_paciente_contado_pelo_id_e_permitido(catalogo):
    """O documento manda contar pacientes por "ID_CONSUMIDOR": isso não
    identifica ninguém e tem de passar."""
    assert validate_sql(
        'SELECT COUNT(DISTINCT "ID_CONSUMIDOR") FROM pbm.fato_pbm_adesoes', catalogo
    ).approved


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT "CPF_CONS" FROM pbm.fato_pbm_transacoes',
        'SELECT "EAN" FROM pbm.fato_pbm_transacoes WHERE "CELULAR" = %s',
        'SELECT "EAN" FROM pbm.fato_pbm_transacoes ORDER BY "NOME_CONS"',
        "SELECT nome FROM audit.rx_cadastro_mais_recente WHERE email IS NOT NULL",
    ],
)
def test_coluna_de_dado_pessoal_e_recusada_em_qualquer_posicao(catalogo, sql):
    """Filtrar ou ordenar por CPF também expõe o dado: quem manda uma
    pergunta por vez descobre o valor pela resposta. Por isso a checagem é
    por posição nenhuma — vale em todas."""
    resultado = validate_sql(sql, catalogo)

    assert not resultado.approved
    assert "dado pessoal" in resultado.reason


def test_select_estrela_em_tabela_com_dado_pessoal_e_recusado(catalogo):
    """`SELECT *` traz CPF e celular sem citá-los em lugar nenhum."""
    resultado = validate_sql("SELECT * FROM pbm.fato_pbm_transacoes", catalogo)

    assert not resultado.approved
    assert "SELECT *" in resultado.reason


def test_select_estrela_em_tabela_sem_dado_pessoal_e_permitido(catalogo):
    assert validate_sql("SELECT * FROM cddd.pdvs", catalogo).approved


def test_coluna_bloqueada_de_outra_tabela_nao_atrapalha(catalogo):
    """`celular` só é bloqueada no cadastro de médicos. Bloquear o nome em
    qualquer tabela deixaria consultas legítimas sem resposta."""
    assert validate_sql("SELECT celular FROM cddd.pdvs", catalogo).approved


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(10)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT dblink('host=x', 'SELECT 1')",
    ],
)
def test_funcao_administrativa_e_recusada(catalogo, sql):
    """pg_sleep segura a conexão, pg_read_file lê arquivo do servidor e
    dblink abre conexão para fora."""
    resultado = validate_sql(sql, catalogo)

    assert not resultado.approved
    assert "não é permitida" in resultado.reason


def test_funcoes_de_texto_usadas_nas_referencias_sao_permitidas(catalogo):
    """A E06 usa translate, upper e split_part para comparar cidades sem
    acento. Um bloqueio amplo demais de função quebraria a referência."""
    resultado = validate_sql(
        "SELECT split_part(translate(upper(cidade), 'Ç', 'C'), ' ', 1) AS cidade "
        "FROM cddd.utc",
        catalogo,
    )

    assert resultado.approved


def test_trava_de_linha_e_recusada(catalogo):
    """FOR UPDATE pede lock e segura transação de outro sistema que usa o
    mesmo banco."""
    resultado = validate_sql("SELECT cod_pdv FROM cddd.pdvs FOR UPDATE", catalogo)

    assert not resultado.approved


@pytest.mark.parametrize("sql", ["", "   ", "isto não é sql"])
def test_consulta_vazia_ou_sem_sentido_e_recusada(catalogo, sql):
    assert not validate_sql(sql, catalogo).approved


def test_limite_de_linhas_pede_uma_linha_a_mais(catalogo):
    """A linha extra é o que distingue "cabe no limite" de "foi cortado": sem
    ela, uma resposta poderia apresentar 500 linhas como se fossem o total."""
    resultado = validate_sql("SELECT und FROM cddd.vendas_consolidado", catalogo, max_rows=10)

    assert resultado.approved
    assert resultado.sql.strip().endswith("LIMIT 11")


def test_consulta_original_e_preservada(catalogo):
    """O SQL executado é o mesmo que a IA escreveu, só embrulhado: reemitir a
    partir da árvore poderia mudar um cast ou um FILTER e alterar o número
    sem ninguém perceber."""
    sql = "SELECT SUM(und) FILTER (WHERE uf = 'MG')::numeric AS mg FROM cddd.vendas_consolidado"

    resultado = validate_sql(sql, catalogo)

    assert sql in resultado.sql


def test_ponto_e_virgula_final_nao_atrapalha(catalogo):
    resultado = validate_sql("SELECT qtd FROM cddd.vw_sellout_mensal;", catalogo)

    assert resultado.approved
    assert ";" not in resultado.sql


def test_todas_as_consultas_de_referencia_sao_aprovadas(catalogo):
    """Referência que o próprio validador recusaria seria bug de catálogo: a
    IA parte delas, e ela nunca conseguiria executar o que copiou."""
    reprovadas = {
        r.id: validate_sql(r.sql, catalogo).reason
        for r in catalogo.references
        if not validate_sql(r.sql, catalogo).approved
    }

    assert reprovadas == {}
    assert len(catalogo.references) >= 20


def test_count_estrela_em_tabela_com_dado_pessoal_e_permitido(catalogo):
    """COUNT(*) só conta linhas. Tratá-lo como SELECT * recusou dez consultas
    de referência do PBM e do painel na primeira conferência contra o banco
    real (2026-09-16)."""
    assert validate_sql(
        "SELECT COUNT(*) AS adesoes FROM pbm.fato_pbm_adesoes", catalogo
    ).approved


def test_estrela_de_tabela_com_dado_pessoal_continua_recusada(catalogo):
    """`t.*` traz as colunas pessoais do mesmo jeito que `*`."""
    assert not validate_sql(
        "SELECT t.* FROM pbm.fato_pbm_transacoes t", catalogo
    ).approved


def test_schema_previsto_passa_no_validador(catalogo):
    """Metas ainda não existem no banco. A consulta precisa chegar ao banco
    para ele responder que o objeto não existe — é daí que sai a resposta de
    "informação ainda não disponível"."""
    assert validate_sql(
        "SELECT mes, fat_alvo_bonus FROM remuneracao_fv.fato_remuneracao", catalogo
    ).approved
