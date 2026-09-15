"""Leitura de configuração por variável de ambiente.

Funções puras (recebem o mapeamento de ambiente) para poderem ser testadas
sem mexer no ambiente do processo.
"""

import os
from collections.abc import Mapping
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

# Hosts que indicam o banco de negócio (Amazon RDS). O banco da aplicação
# nunca pode apontar para eles — ver assert_not_business_database.
_BUSINESS_DATABASE_HOST_MARKERS = (".rds.amazonaws.com",)

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


def assert_not_business_database(host: str) -> None:
    """Recusa subir a aplicação com o banco dela apontando para o RDS.

    O banco de negócio nunca entra em `DATABASES` (ADR-0002): se entrasse, um
    `migrate` criaria as tabelas do Django dentro dele e a suíte de testes
    criaria e apagaria bancos `test_*` no servidor de produção. Um erro na
    subida é barato; qualquer uma dessas duas coisas, não.
    """
    normalized = (host or "").strip().lower()
    if any(marker in normalized for marker in _BUSINESS_DATABASE_HOST_MARKERS):
        raise ImproperlyConfigured(
            f"O banco da aplicação aponta para {host!r}, que parece ser o RDS do "
            "banco de negócio. A aplicação precisa de um Postgres próprio "
            "(APP_DATABASE_URL / APP_DB_*); o RDS é acessado só pelo executor "
            "somente leitura via ANALYTICS_DATABASE_URL (ADR-0002)."
        )


def database_from_env(environ: Mapping = os.environ) -> dict:
    """Configuração do banco da APLICAÇÃO (conversas e auditoria).

    Só lê variáveis com prefixo `APP_`, de propósito. O `bi/.env` já existia
    com credenciais da AWS antes deste código, e nomes genéricos como
    `DATABASE_URL` ou `POSTGRES_HOST` podem estar lá apontando para o RDS.

    `APP_DATABASE_URL`, quando preenchida, vence as `APP_DB_*` — é o formato
    que o Railway entrega. Os padrões servem ao Postgres do docker-compose.
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

    assert_not_business_database(config["HOST"])
    return config
