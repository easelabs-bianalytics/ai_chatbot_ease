"""O que o Jarvis está fazendo agora, para a tela mostrar (ADR-0025).

Uma investigação leva de um a três minutos: várias rodadas de hipóteses,
cada uma com suas consultas. "Pensando…" parado esse tempo todo parece
travamento. Aqui fica uma frase curta — "Vendo se a queda foi geral ou
concentrada" — que o polling da tela lê junto com a pergunta pendente.

Mora no cache (o Redis da task), com prazo: é estado de passagem, não
registro. O registro de verdade é a auditoria da resposta.
"""

from django.core.cache import cache

SEGUNDOS = 10 * 60
MAX_CARACTERES = 160


def _chave(message_id: int) -> str:
    return f"progresso:{message_id}"


def definir(message_id: int, texto: str) -> None:
    """Falha aqui nunca derruba a resposta: progresso é cortesia."""
    try:
        cache.set(_chave(message_id), " ".join(str(texto).split())[:MAX_CARACTERES], timeout=SEGUNDOS)
    except Exception:  # noqa: BLE001 — cache fora do ar não pode parar a investigação
        pass


def ler(message_id: int) -> str:
    try:
        return cache.get(_chave(message_id)) or ""
    except Exception:  # noqa: BLE001
        return ""


def limpar(message_id: int) -> None:
    try:
        cache.delete(_chave(message_id))
    except Exception:  # noqa: BLE001
        pass
