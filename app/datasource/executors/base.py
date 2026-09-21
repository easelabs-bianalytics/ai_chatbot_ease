"""Interface abstrata do executor de consultas (ADR-0005).

O orquestrador conhece só este contrato: nos testes roda o fake, em produção
o executor somente leitura contra o RDS. Erros nativos do psycopg2 são
traduzidos aqui para que nenhuma camada acima precise conhecer o driver.
"""

import datetime
import decimal
from abc import ABC, abstractmethod
from dataclasses import dataclass


class QueryExecutionError(Exception):
    """Falha ao executar a consulta (erro de SQL, coluna inexistente, banco
    fora do ar). A mensagem volta para a IA na correção única (ADR-0014),
    então precisa ser legível."""


class QueryTimeout(QueryExecutionError):
    """A consulta passou do tempo permitido e foi cancelada pelo banco."""


class QueryUnavailable(QueryExecutionError):
    """O banco não respondeu: conexão recusada, perdida ou fora do ar.

    Não é erro da consulta, então não vai para a correção da IA: reescrever
    um SQL certo porque o banco caiu só gasta uma chamada de modelo — foram
    US$ 0,094 no teste de 2026-09-21, quando o túnel caiu no meio.
    """


class QueryObjectMissing(QueryExecutionError):
    """A consulta cita tabela, view ou schema que não existe no banco.

    Tratado à parte porque a regra do time de BI é não trocar por outra
    tabela parecida nem estimar: a resposta é que a informação ainda não
    está disponível (ex.: metas, cujo schema ainda não foi criado).
    """


def jsonable(valor):
    """Converte o valor do banco em algo que cabe em JSON.

    Decimal vira float porque o número precisa ser comparável na checagem de
    ancoragem (ADR-0010) e legível para o modelo; data vira ISO."""
    if isinstance(valor, decimal.Decimal):
        return float(valor)
    if isinstance(valor, (datetime.datetime, datetime.date, datetime.time)):
        return valor.isoformat()
    if isinstance(valor, (bytes, memoryview)):
        return "<binário>"
    return valor


@dataclass(frozen=True)
class QueryResult:
    columns: tuple
    rows: tuple
    truncated: bool
    duration_ms: int

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def as_dicts(self, limit: int | None = None) -> list:
        linhas = self.rows if limit is None else self.rows[:limit]
        return [dict(zip(self.columns, linha)) for linha in linhas]


class QueryExecutor(ABC):
    @abstractmethod
    def run(self, sql: str, max_rows: int | None = None) -> QueryResult:
        """Executa a consulta já aprovada pelo validador.

        `max_rows` serve para detectar truncamento: o validador pede uma linha
        a mais que o limite, e o que passar disso é cortado aqui.
        """
