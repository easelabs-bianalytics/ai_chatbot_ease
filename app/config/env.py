"""Leitura de configuração por variável de ambiente.

Funções puras (recebem o mapeamento de ambiente) para poderem ser testadas
sem mexer no ambiente do processo.
"""

import os
import re
from collections.abc import Mapping
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

# Hosts do Amazon RDS. Em produção o banco da aplicação É o RDS — o schema
# `jarvis` dentro do `easelabs` (ADR-0002, revista em 2026-09-21). A suíte de
# testes é que nunca pode apontar para ele: ver recusar_rds_nos_testes.
_RDS_HOST_MARKERS = (".rds.amazonaws.com",)

# O schema do Jarvis no banco de produção. A role `jarvis_app` já tem o
# search_path fixado nele; a aplicação repete na conexão, cinto e
# suspensório.
SCHEMA_DE_PRODUCAO = "jarvis"

_TRUE_VALUES = {"1", "true", "yes", "on"}


def env_bool(name: str, default: bool = False, environ: Mapping = os.environ) -> bool:
    raw = (environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in _TRUE_VALUES


def env_list(name: str, default: str = "", environ: Mapping = os.environ) -> list[str]:
    raw = environ.get(name)
    if raw is None:
        raw = default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _e_rds(host: str) -> bool:
    normalized = (host or "").strip().lower()
    return any(marker in normalized for marker in _RDS_HOST_MARKERS)


def recusar_rds_nos_testes(host: str) -> None:
    """A suíte de testes nunca aponta para o RDS.

    O pytest-django cria e apaga bancos `test_*` no servidor configurado.
    Apontado para o RDS de produção, isso aconteceria na instância do cockpit
    inteiro. É a proteção da ADR-0002 que continua valendo quando o banco da
    aplicação passou a ser um schema no próprio RDS (a outra — o `migrate`
    não sair do schema — é privilégio de banco, na role `jarvis_app`).
    """
    if _e_rds(host):
        raise ImproperlyConfigured(
            f"Os testes estão apontando para {host!r}, que é o RDS de produção. "
            "A suíte cria e apaga bancos test_* no servidor configurado: use o "
            "Postgres local (docker-compose) ou TEST_APP_DATABASE_URL local."
        )


def database_from_env(environ: Mapping = os.environ, *, para_testes: bool = False) -> dict:
    """Configuração do banco da APLICAÇÃO (conversas e auditoria).

    Só lê variáveis com prefixo `APP_`, de propósito. O `bi/.env` já existia
    com credenciais da AWS antes deste código, e nomes genéricos como
    `DATABASE_URL` ou `POSTGRES_HOST` podem estar lá apontando para o RDS.

    `APP_DATABASE_URL`, quando preenchida, vence as `APP_DB_*`. Os padrões
    servem ao Postgres do docker-compose.

    Schema: com host de RDS, a conexão fica presa ao `jarvis` pelo
    search_path; `APP_DB_SCHEMA` escolhe outro, ou força o mesmo quando o RDS
    é alcançado pelo túnel (host 127.0.0.1). No Postgres local fica o
    `public`, sem nada a configurar.
    """
    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": environ.get("APP_DB_NAME", "bi_chatbot"),
        "USER": environ.get("APP_DB_USER", "bi_chatbot"),
        "PASSWORD": environ.get("APP_DB_PASSWORD", "bi_chatbot_dev"),
        "HOST": environ.get("APP_DB_HOST", "localhost"),
        "PORT": environ.get("APP_DB_PORT", "5434"),
    }

    url = (environ.get("APP_DATABASE_URL") or "").strip()
    if url:
        parsed = urlparse(url)
        config.update(
            NAME=parsed.path.lstrip("/") or "postgres",
            USER=unquote(parsed.username or ""),
            PASSWORD=unquote(parsed.password or ""),
            HOST=parsed.hostname or "",
            PORT=str(parsed.port or 5432),
        )

    if para_testes:
        recusar_rds_nos_testes(config["HOST"])
        return config

    schema = (environ.get("APP_DB_SCHEMA") or "").strip()
    if not schema and _e_rds(config["HOST"]):
        schema = SCHEMA_DE_PRODUCAO
    if schema:
        # Vai parar num parâmetro de conexão: só nome de identificador.
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
            raise ImproperlyConfigured(f"APP_DB_SCHEMA inválido: {schema!r}")
        config["OPTIONS"] = {"options": f"-c search_path={schema}"}

    # Conexão reaproveitada por 60 s em vez de uma nova a cada requisição: o
    # polling da tela pergunta a cada poucos segundos, e cada conexão nova ao
    # RDS custa um handshake TLS. A checagem de saúde descarta a conexão que o
    # banco tiver derrubado, em vez de estourar erro na requisição seguinte.
    config["CONN_MAX_AGE"] = 60
    config["CONN_HEALTH_CHECKS"] = True
    return config
