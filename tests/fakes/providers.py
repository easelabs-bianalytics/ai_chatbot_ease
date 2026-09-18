"""Provedores de IA programáveis para os testes.

O `FakeAIProvider` de produção casa a pergunta com as referências e é bom
para o caminho feliz. Aqui é o contrário: cada teste programa exatamente o
que a IA vai devolver — inclusive resposta errada e exceção — para exercitar
os ramos que só aparecem quando o modelo erra.
"""

from ai_orchestrator.providers.base import (
    AIProvider,
    AIUsage,
    Answer,
    AnswerRequest,
    Plan,
    PlanRequest,
)


def plano(sql="SELECT und FROM cddd.vendas_consolidado", **campos) -> Plan:
    padrao = {
        "intent": Plan.Intent.ANSWER_WITH_DATA,
        "sql": sql,
        "reference_query_id": "Q10",
        "reason": "teste",
        "usage": AIUsage(model="stub", tokens_input=100, tokens_output=10, cost_estimate=0.001, latency_ms=20),
    }
    padrao.update(campos)
    return Plan(**padrao)


def resposta(reply="foram 47 unidades", **campos) -> Answer:
    padrao = {
        "reply": reply,
        "resolution": "answered",
        "usage": AIUsage(model="stub", tokens_input=200, tokens_output=30, cost_estimate=0.002, latency_ms=30),
    }
    padrao.update(campos)
    return Answer(**padrao)


class ScriptedAIProvider(AIProvider):
    """Devolve planos e respostas pré-definidos, em ordem, e guarda o que
    recebeu. Item que seja exceção é levantado."""

    def __init__(self, planos=(), respostas=()):
        self._planos = list(planos)
        self._respostas = list(respostas)
        self.plan_requests = []
        self.answer_requests = []

    def plan(self, request: PlanRequest) -> Plan:
        self.plan_requests.append(request)
        return self._proximo(self._planos, "plano")

    def answer(self, request: AnswerRequest) -> Answer:
        self.answer_requests.append(request)
        return self._proximo(self._respostas, "resposta")

    @staticmethod
    def _proximo(fila, nome):
        if not fila:
            raise AssertionError(f"o teste não programou {nome} suficiente")
        proximo = fila.pop(0)
        if isinstance(proximo, Exception):
            raise proximo
        return proximo
