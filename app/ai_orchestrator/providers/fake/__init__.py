"""Provedor determinístico, sem rede e sem custo (ADR-0005).

Casa a pergunta com as consultas de referência por palavra-chave do título.
Não entende pergunta nenhuma de verdade — e não precisa: ele existe para
exercitar o pipeline do orquestrador (validador, executor, ancoragem,
registro) sem depender da OpenAI. O que valida o texto da IA é a suíte de
casos sintéticos com o provedor real (Fase 7).
"""

import re
import unicodedata

from ai_orchestrator.providers.base import (
    AIProvider,
    AIProviderError,
    Answer,
    AnswerRequest,
    AIUsage,
    Plan,
    PlanRequest,
)
from catalog.loader import get_catalog

MODELO = "fake-provider"

_PEDIDO_DE_ESCLARECIMENTO = "De qual período você precisa? (ex.: agosto de 2026)"


def _normalize(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")


def _palavras(texto: str) -> set:
    return {p for p in re.findall(r"[a-z0-9_]+", _normalize(texto)) if len(p) >= 4}


class FakeAIProvider(AIProvider):
    def __init__(self, catalog=None):
        self._catalog = catalog or get_catalog()

    def _melhor_referencia(self, pergunta: str):
        palavras = _palavras(pergunta)
        melhor, melhor_nota = None, 0
        for referencia in self._catalog.references:
            nota = len(palavras & _palavras(referencia.title))
            if nota > melhor_nota:
                melhor, melhor_nota = referencia, nota
        return melhor

    def plan(self, request: PlanRequest) -> Plan:
        referencia = self._melhor_referencia(request.question)
        if referencia is None:
            return Plan(
                intent=Plan.Intent.UNKNOWN,
                reason="nenhuma consulta de referência trata desse assunto",
                usage=AIUsage(model=MODELO),
            )

        # Uma referência sem parâmetro roda como está; com parâmetro, o fake
        # não tem como preenchê-lo e pede esclarecimento.
        if ":" in referencia.sql.replace("::", ""):
            return Plan(
                intent=Plan.Intent.CLARIFY,
                clarification_question=_PEDIDO_DE_ESCLARECIMENTO,
                reference_query_id=referencia.id,
                reason="a consulta de referência exige parâmetros",
                usage=AIUsage(model=MODELO),
            )

        return Plan(
            intent=Plan.Intent.ANSWER_WITH_DATA,
            sql=referencia.sql,
            reference_query_id=referencia.id,
            reason=f"usa a referência {referencia.id}",
            usage=AIUsage(model=MODELO, tokens_input=len(request.question.split())),
        )

    def answer(self, request: AnswerRequest) -> Answer:
        """Transcreve o resultado, sem narrativa.

        Assim a resposta do fake sempre passa pela checagem de ancoragem —
        ela não tem como citar número que não veio do banco."""
        linhas = [
            "; ".join(f"{coluna}: {valor}" for coluna, valor in zip(request.columns, linha))
            for linha in request.rows[:5]
        ]
        texto = "\n".join(linhas) if linhas else "Sem linhas."
        return Answer(reply=texto, resolution="answered", usage=AIUsage(model=MODELO))


class FailingAIProvider(AIProvider):
    """Simula a IA fora do ar, para o tratamento de falha ser testado sem
    depender de um provedor real."""

    def __init__(self, mensagem: str = "falha simulada do provedor de IA"):
        self._mensagem = mensagem

    def plan(self, request: PlanRequest) -> Plan:
        raise AIProviderError(self._mensagem)

    def answer(self, request: AnswerRequest) -> Answer:
        raise AIProviderError(self._mensagem)
