"""Executor de mentira: resultados e falhas programados, sem banco nenhum.

Os testes do orquestrador precisam exercitar resultado vazio, truncado,
erro e timeout — cenários que seriam difíceis e lentos de provocar num banco
real, e que não podem depender de rede (ADR-0005).
"""

from datasource.executors.base import QueryExecutor, QueryResult


def make_result(columns, rows, truncated=False, duration_ms=1) -> QueryResult:
    return QueryResult(
        columns=tuple(columns),
        rows=tuple(tuple(linha) for linha in rows),
        truncated=truncated,
        duration_ms=duration_ms,
    )


VAZIO = make_result(("valor",), [])


class FakeQueryExecutor(QueryExecutor):
    def __init__(self, resultados=None):
        """`resultados` são consumidos em ordem, um por execução. Um item que
        seja exceção é levantado, o que é como se programa uma falha."""
        self._resultados = list(resultados or [])
        self.executed = []

    def run(self, sql: str, max_rows: int | None = None) -> QueryResult:
        self.executed.append(sql)

        if not self._resultados:
            return make_result(("valor",), [(1,)])

        proximo = self._resultados.pop(0)
        if isinstance(proximo, Exception):
            raise proximo
        return proximo
