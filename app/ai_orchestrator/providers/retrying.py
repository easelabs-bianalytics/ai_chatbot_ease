"""Nova tentativa com espera crescente, em volta do provedor real (ADR-0005).

Falha de rede e limite de requisições são normais numa API externa, e não
podem virar "tive um problema técnico" na cara do usuário. O que não se
repete é erro de contrato (o modelo devolveu uma intenção que não existe):
repetir só gastaria de novo.
"""

import logging
import time

from ai_orchestrator.providers.base import AIOutputTruncated, AIProvider, AIProviderError, AIQuotaExceeded

logger = logging.getLogger(__name__)

TENTATIVAS = 3
ESPERA_INICIAL = 1.0


class RetryingAIProvider(AIProvider):
    def __init__(self, inner: AIProvider, tentativas: int = TENTATIVAS,
                 espera_inicial: float = ESPERA_INICIAL, dormir=time.sleep):
        self._inner = inner
        self._tentativas = max(1, tentativas)
        self._espera = espera_inicial
        self._dormir = dormir

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", "")

    @property
    def answer_model(self) -> str:
        return getattr(self._inner, "answer_model", "")

    def plan(self, request):
        return self._com_retry(self._inner.plan, request, "planejamento")

    def answer(self, request):
        return self._com_retry(self._inner.answer, request, "redação")

    def read_image(self, request):
        return self._com_retry(self._inner.read_image, request, "leitura da imagem")

    def _com_retry(self, funcao, request, etapa: str):
        espera = self._espera
        for tentativa in range(1, self._tentativas + 1):
            try:
                return funcao(request)
            except (AIQuotaExceeded, AIOutputTruncated):
                # Sem crédito não volta sozinho, e saída cortada no limite de
                # tokens volta cortada de novo: insistir só pagaria outra vez.
                raise
            except AIProviderError as exc:
                if tentativa == self._tentativas:
                    raise
                logger.warning(
                    "Falha na %s (tentativa %s de %s): %s", etapa, tentativa, self._tentativas, exc
                )
                self._dormir(espera)
                espera *= 2
