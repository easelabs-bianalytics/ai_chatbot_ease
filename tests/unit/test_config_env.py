"""Configuração por variável de ambiente (app/config/env.py)."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.env import assert_not_business_database, database_from_env, env_bool, env_list

RDS_HOST = "ease-bi.c1abcdefgh.us-east-1.rds.amazonaws.com"


def test_banco_da_aplicacao_usa_o_postgres_local_por_padrao():
    config = database_from_env({})

    assert config["HOST"] == "localhost"
    assert config["PORT"] == "5434"
    assert config["NAME"] == "bi_chatbot"


def test_app_database_url_vence_as_variaveis_individuais():
    """O Railway entrega o banco numa URL só; configurar produção deve ser uma
    variável, não cinco que precisam estar todas certas."""
    config = database_from_env(
        {
            "APP_DATABASE_URL": "postgresql://app:s%40nha@postgres.railway.internal:5432/railway",
            "APP_DB_HOST": "outro-host",
        }
    )

    assert config["HOST"] == "postgres.railway.internal"
    assert config["PORT"] == "5432"
    assert config["NAME"] == "railway"
    assert config["USER"] == "app"
    assert config["PASSWORD"] == "s@nha"


def test_variaveis_genericas_de_banco_sao_ignoradas():
    """O bi/.env já existia com credenciais da AWS antes deste código. Nomes
    genéricos como DATABASE_URL ou POSTGRES_HOST podem apontar para o RDS, e
    o `migrate` criaria as tabelas do Django dentro do banco de negócio. O
    banco da aplicação só lê variáveis com prefixo APP_."""
    config = database_from_env(
        {
            "DATABASE_URL": f"postgresql://admin:x@{RDS_HOST}:5432/bi",
            "POSTGRES_HOST": RDS_HOST,
        }
    )

    assert config["HOST"] == "localhost"


@pytest.mark.parametrize("host", [RDS_HOST, RDS_HOST.upper()])
def test_banco_da_aplicacao_nunca_aponta_para_o_rds(host):
    """ADR-0002: o RDS nunca entra em DATABASES. Se alguém colar a URL dele em
    APP_DATABASE_URL, a aplicação se recusa a subir em vez de rodar migrate
    no banco de negócio."""
    with pytest.raises(ImproperlyConfigured):
        database_from_env({"APP_DATABASE_URL": f"postgresql://u:p@{host}:5432/bi"})


def test_hosts_da_aplicacao_sao_aceitos():
    for host in ("localhost", "127.0.0.1", "db", "postgres.railway.internal"):
        assert_not_business_database(host)


@pytest.mark.parametrize(
    "raw, esperado",
    [("1", True), ("true", True), ("ON", True), ("yes", True), ("0", False), ("false", False)],
)
def test_env_bool(raw, esperado):
    assert env_bool("X", environ={"X": raw}) is esperado


def test_env_bool_vazio_usa_o_padrao():
    assert env_bool("X", default=True, environ={"X": ""}) is True
    assert env_bool("X", default=False, environ={}) is False


def test_env_list_ignora_itens_vazios_e_espacos():
    assert env_list("X", environ={"X": " a.com , ,b.com,"}) == ["a.com", "b.com"]
    assert env_list("X", default="localhost", environ={}) == ["localhost"]
