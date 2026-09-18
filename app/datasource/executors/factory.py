"""Escolhe o executor conforme o ambiente.

Aceita as duas formas de configurar o banco de negócio: campos discretos
(convenção da casa para o RDS) ou uma URL única (banco sintético local e
testes). Sem nenhuma das duas, cai no fake — configuração faltando não pode
virar conexão acidental em outro lugar.
"""

import os

from catalog.loader import get_catalog
from datasource.executors.base import QueryExecutor
from datasource.executors.fake import FakeQueryExecutor
from datasource.executors.postgres_readonly import PostgresReadOnlyExecutor


def get_configured_executor() -> QueryExecutor:
    catalogo = get_catalog()
    host = os.environ.get("ANALYTICS_DB_HOST", "").strip()
    dsn = os.environ.get("ANALYTICS_DATABASE_URL", "").strip()

    if not host and not dsn:
        return FakeQueryExecutor()

    return PostgresReadOnlyExecutor(
        dsn=dsn if not host else "",
        host=host,
        port=os.environ.get("ANALYTICS_DB_PORT", "").strip(),
        dbname=os.environ.get("ANALYTICS_DB_NAME", "").strip(),
        user=os.environ.get("ANALYTICS_DB_USER", "").strip(),
        password=os.environ.get("ANALYTICS_DB_PASS", ""),
        sslmode=os.environ.get("ANALYTICS_DB_SSLMODE", "require").strip(),
        statement_timeout_ms=catalogo.statement_timeout_ms,
    )
