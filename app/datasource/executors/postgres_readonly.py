"""Executor somente leitura do banco de negócio (ADR-0008, camadas 1 e 2).

Único ponto do sistema que abre conexão com o banco de negócio. Não usa o ORM
do Django de propósito: esse banco não está em DATABASES, então não existe
caminho para um `migrate` ou um `save()` chegar até ele (ADR-0002).

Cada execução abre uma transação somente leitura, com tempo máximo, e termina
em rollback. Isso vale mesmo que o usuário do banco esteja configurado errado
— é a segunda camada de proteção, independente da primeira.

A conexão aceita campos discretos (host, porta, banco, usuário, senha), que é
a convenção da casa para o RDS, e também uma URL única, usada pelo banco
sintético local e pelos testes.
"""

import os
import time

import psycopg2
from psycopg2 import errors as pg_errors

from datasource.executors.base import (
    QueryExecutionError,
    QueryExecutor,
    QueryObjectMissing,
    QueryResult,
    QueryTimeout,
    jsonable,
)

DEFAULT_CONNECT_TIMEOUT_SECONDS = 15
DEFAULT_LOCK_TIMEOUT_MS = 10000


class PostgresReadOnlyExecutor(QueryExecutor):
    def __init__(
        self,
        dsn=None,
        host=None,
        port=None,
        dbname=None,
        user=None,
        password=None,
        sslmode=None,
        statement_timeout_ms=15000,
        lock_timeout_ms=DEFAULT_LOCK_TIMEOUT_MS,
        connect_timeout=None,
    ):
        self._dsn = (dsn or "").strip()
        self._campos = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
            "sslmode": sslmode,
        }
        self._statement_timeout_ms = int(statement_timeout_ms)
        self._lock_timeout_ms = int(lock_timeout_ms)
        self._connect_timeout = int(connect_timeout or DEFAULT_CONNECT_TIMEOUT_SECONDS)

    def _parametros(self) -> dict:
        # Aplicados na própria conexão, além do SET LOCAL: se a sessão cair
        # antes do SET, ela já nasce limitada. lock_timeout evita que a
        # consulta fique presa esperando um lock de outro sistema.
        comuns = {
            "connect_timeout": self._connect_timeout,
            "options": (
                f"-c statement_timeout={self._statement_timeout_ms} "
                f"-c lock_timeout={self._lock_timeout_ms}"
            ),
        }
        if self._dsn:
            return {"dsn": self._dsn, **comuns}

        campos = {k: v for k, v in self._campos.items() if v not in (None, "")}
        if not campos.get("host"):
            raise QueryExecutionError(
                "banco de negócio não configurado: defina ANALYTICS_DB_HOST e "
                "companhia, ou ANALYTICS_DATABASE_URL"
            )
        campos["port"] = int(campos.get("port") or 5432)
        return {**campos, **comuns}

    def run(self, sql: str, max_rows: int | None = None) -> QueryResult:
        parametros = self._parametros()

        try:
            conexao = psycopg2.connect(**parametros)
        except psycopg2.Error as exc:
            raise QueryExecutionError(f"não foi possível conectar ao banco: {_limpa(exc)}") from exc

        try:
            # Camada 2 do ADR-0008: a transação é somente leitura mesmo que a
            # permissão do usuário esteja frouxa.
            conexao.set_session(readonly=True, autocommit=False)
            with conexao.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", (self._statement_timeout_ms,))
                inicio = time.monotonic()
                try:
                    cursor.execute(sql)
                except pg_errors.QueryCanceled as exc:
                    raise QueryTimeout(
                        f"a consulta passou de {self._statement_timeout_ms} ms e foi "
                        "cancelada; filtre um período menor ou agregue mais"
                    ) from exc
                except (pg_errors.UndefinedTable, pg_errors.InvalidSchemaName) as exc:
                    raise QueryObjectMissing(_limpa(exc)) from exc
                except psycopg2.Error as exc:
                    raise QueryExecutionError(_limpa(exc)) from exc

                duracao_ms = int((time.monotonic() - inicio) * 1000)
                colunas = tuple(coluna.name for coluna in cursor.description or ())
                linhas = cursor.fetchall()
            conexao.rollback()
        finally:
            conexao.close()

        truncado = max_rows is not None and len(linhas) > max_rows
        if truncado:
            linhas = linhas[:max_rows]

        return QueryResult(
            columns=colunas,
            rows=tuple(tuple(jsonable(valor) for valor in linha) for linha in linhas),
            truncated=truncado,
            duration_ms=duracao_ms,
        )


def _limpa(exc: Exception) -> str:
    """Mensagem do Postgres em uma linha: ela vai para a IA e para o log."""
    return " ".join(str(exc).split())
