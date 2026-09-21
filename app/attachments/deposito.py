"""Depósito temporário dos bytes do anexo.

Usa o cache do Django, que em produção é o Redis que já roda dentro da task
(o mesmo do Celery, em outro banco) e nos testes é memória local. Não é
armazenamento: é uma gaveta com prazo. Nada disso vai para disco, S3 ou
banco — ver a nota 1 do `attachments/__init__.py`.

O prazo é a garantia de que "descartamos internamente" não depende de
alguém lembrar de apagar: se o worker morrer no meio, o Redis esquece
sozinho.
"""

import uuid

from django.core.cache import cache

from attachments.limites import SEGUNDOS_DA_ENTRADA

PREFIXO = "anexo"


def _chave(token: str) -> str:
    return f"{PREFIXO}:{token}"


def guardar(dados: bytes, *, segundos: int = SEGUNDOS_DA_ENTRADA) -> str:
    """Guarda os bytes e devolve o token que os encontra.

    O token é aleatório e não deriva do nome do arquivo nem do usuário: ele
    trafega até o navegador, e um token adivinhável deixaria uma pessoa
    baixar a planilha de outra.
    """
    token = uuid.uuid4().hex
    cache.set(_chave(token), dados, timeout=segundos)
    return token


def buscar(token: str) -> bytes | None:
    """Os bytes, ou None se o prazo venceu. Vencer é normal, não é erro:
    quem chama tem de ter um caminho honesto para esse caso."""
    if not token:
        return None
    return cache.get(_chave(token))


def prolongar(token: str, *, segundos: int) -> bool:
    """Renova o prazo, contando de agora. False se já tinha vencido.

    Usado quando o Jarvis devolve uma pergunta ("painel atual ou território?")
    antes de preencher: a planilha precisa sobreviver até a resposta."""
    return bool(token) and bool(cache.touch(_chave(token), timeout=segundos))


def descartar(token: str) -> None:
    if token:
        cache.delete(_chave(token))
