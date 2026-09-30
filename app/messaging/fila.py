"""Uma pergunta de cada vez por conversa, na ordem de chegada (2026-09-30).

O worker atende várias perguntas ao mesmo tempo (`-P threads`), porque quase
todo o tempo de uma resposta é espera pela OpenAI e pelo banco. Conversas
diferentes andam em paralelo; dentro da MESMA conversa (um chat do WhatsApp,
uma conversa do chat web), as perguntas são atendidas uma de cada vez, na
ordem em que chegaram. Duas em paralelo na mesma conversa veriam uma à outra
pela metade no histórico — a segunda leria a primeira ainda sem resposta — e
é daí que viria a resposta misturada.

No WhatsApp a mensagem só é gravada depois da espera sorteada, então a ordem
é uma senha tirada na chegada ao webhook (`tirar_senha`), guardada no Redis.
A tarefa só atende na sua vez (`e_a_vez`) e passa a vez ao terminar
(`passar_a_vez`), respondendo, ignorando ou falhando. Se a vez não anda por
`ESPERA_MAXIMA_S` (o worker caiu no meio de uma tarefa), a fila pula a senha
perdida em vez de travar a conversa para sempre.
"""

import time

from django.core.cache import cache

# Mais que a resposta mais longa (uma investigação leva uns 3 minutos): até
# aqui, quem espera é porque a da frente ainda está sendo respondida.
ESPERA_MAXIMA_S = 8 * 60
# De quanto em quanto tempo a tarefa que espera olha de novo se é a vez dela.
REVER_EM_S = 2


def _chaves(conversa: str) -> tuple:
    return f"fila:{conversa}:senha", f"fila:{conversa}:vez", f"fila:{conversa}:desde"


def tirar_senha(conversa: str) -> int:
    """A posição desta mensagem na fila da conversa (1, 2, 3…)."""
    senha, vez, desde = _chaves(conversa)
    cache.add(senha, 0, timeout=None)
    cache.add(vez, 1, timeout=None)
    cache.add(desde, time.time(), timeout=None)
    return cache.incr(senha)


def e_a_vez(conversa: str, numero: int) -> bool:
    _, vez, desde = _chaves(conversa)
    atual = cache.get(vez)
    if atual is None or numero <= atual:
        # Sem fila (o Redis reiniciou) ou senha já chamada: pode atender.
        return True
    if time.time() - (cache.get(desde) or 0) > ESPERA_MAXIMA_S:
        # A da frente se perdeu: segue com esta, que é a próxima que chegou.
        cache.set(vez, numero, timeout=None)
        cache.set(desde, time.time(), timeout=None)
        return True
    return False


def passar_a_vez(conversa: str, numero: int) -> None:
    _, vez, desde = _chaves(conversa)
    atual = cache.get(vez) or 1
    if numero >= atual:
        cache.set(vez, numero + 1, timeout=None)
        cache.set(desde, time.time(), timeout=None)


def tem_depois(conversa: str, numero: int) -> bool:
    """Já chegou outra mensagem nesta conversa depois da senha `numero`."""
    if not (conversa and numero):
        return False
    senha, _, _ = _chaves(conversa)
    return (cache.get(senha) or 0) > numero
