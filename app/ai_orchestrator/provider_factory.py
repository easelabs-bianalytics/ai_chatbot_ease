"""Escolhe o provedor de IA conforme o ambiente (ADR-0005, ADR-0016).

`AI_PROVIDER=openai` liga o modelo real; qualquer outro valor (ou nenhum)
deixa o fake, que é o que a suíte de testes e o desenvolvimento local usam.
O provedor real nunca vai sozinho: vai embrulhado no retry, porque falha de
rede não pode virar "tive um problema técnico" para o usuário.
"""

import os

from ai_orchestrator.providers.base import AIProvider
from ai_orchestrator.providers.fake import FakeAIProvider
from ai_orchestrator.providers.retrying import TENTATIVAS, RetryingAIProvider


def _tentativas() -> int:
    bruto = os.environ.get("AI_PROVIDER_MAX_ATTEMPTS", "").strip()
    try:
        return max(1, int(bruto))
    except ValueError:
        return TENTATIVAS


def get_configured_provider() -> AIProvider:
    escolhido = os.environ.get("AI_PROVIDER", "").strip().lower()
    if escolhido in ("", "fake"):
        return FakeAIProvider()
    if escolhido == "openai":
        # Importado aqui dentro: o módulo puxa o SDK e o catálogo, e quem
        # roda com o fake não precisa de nenhum dos dois.
        from ai_orchestrator.providers.openai_provider import OpenAIProvider

        return RetryingAIProvider(OpenAIProvider(), tentativas=_tentativas())
    raise NotImplementedError(
        f"provedor {escolhido!r} não existe; use 'openai' ou 'fake' (ADR-0016)"
    )
