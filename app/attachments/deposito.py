"""Depósito dos bytes do anexo e da planilha devolvida.

O cache do Django (em produção, o Redis da própria task) é a gaveta rápida,
com prazo. Desde 2026-10-05 (ADR-0034) ele não é mais o único lugar: o arquivo
que entra numa conversa é **fixado** — vai para o S3, numa pasta da conversa,
com um registro `ArquivoDaConversa` — e `buscar` volta a ele quando o Redis
esqueceu (prazo vencido ou deploy, que recria a task e o Redis junto).

O arquivo fica enquanto a conversa existir, até dois anos (ciclo de vida do
bucket). Apagar a conversa apaga os arquivos dela de verdade.
"""

import logging
import uuid

from django.core.cache import cache

from attachments.limites import SEGUNDOS_DA_ENTRADA, SEGUNDOS_DA_PLANILHA_NA_CONVERSA

logger = logging.getLogger(__name__)

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
    dados = cache.get(_chave(token))
    if dados is not None:
        return dados
    return _do_armazem(token)


def _do_armazem(token: str) -> bytes | None:
    """O arquivo fixado na conversa, quando o Redis já o esqueceu. Volta para
    o Redis, para o próximo uso não ir ao S3."""
    from attachments.armazem import armazem
    from messaging.models import ArquivoDaConversa

    registro = (ArquivoDaConversa.objects.filter(token=token, conversation__deleted_at__isnull=True)
                .only("chave").first())
    if registro is None:
        return None
    try:
        dados = armazem().buscar(registro.chave)
    except Exception:
        logger.warning("Não consegui buscar o arquivo %s no armazém", registro.chave, exc_info=True)
        return None
    if dados is not None:
        cache.set(_chave(token), dados, timeout=SEGUNDOS_DA_PLANILHA_NA_CONVERSA)
    return dados


def fixar(token: str, *, conversa, papel: str, nome: str = "", mensagem=None) -> bool:
    """Guarda na conversa, sem prazo, o arquivo que está no Redis.

    Falhar aqui nunca impede a pergunta: o arquivo continua no Redis e a
    conversa segue como antes, só sem a garantia de sobreviver ao deploy."""
    from attachments.armazem import armazem
    from messaging.models import ArquivoDaConversa

    if not token or ArquivoDaConversa.objects.filter(token=token).exists():
        return bool(token)
    dados = cache.get(_chave(token))
    if dados is None:
        return False
    chave = f"conversas/{conversa.pk}/{token}"
    try:
        armazem().guardar(chave, dados)
        ArquivoDaConversa.objects.create(conversation=conversa, message=mensagem, token=token, papel=papel,
                                         nome=(nome or "")[:255], tamanho=len(dados), chave=chave)
    except Exception:
        logger.warning("Não consegui guardar o arquivo da conversa %s", conversa.pk, exc_info=True)
        return False
    return True


def apagar_da_conversa(conversa) -> int:
    """Apaga de verdade os arquivos da conversa: do S3, do Redis e o
    registro. Devolve quantos eram."""
    from attachments.armazem import armazem
    from messaging.models import ArquivoDaConversa

    registros = list(ArquivoDaConversa.objects.filter(conversation=conversa))
    if not registros:
        return 0
    armazem().apagar(r.chave for r in registros)
    for registro in registros:
        cache.delete(_chave(registro.token))
    ArquivoDaConversa.objects.filter(pk__in=[r.pk for r in registros]).delete()
    return len(registros)


def prolongar(token: str, *, segundos: int) -> bool:
    """Renova o prazo, contando de agora. False se já tinha vencido.

    Usado quando o Jarvis devolve uma pergunta ("painel atual ou território?")
    antes de preencher: a planilha precisa sobreviver até a resposta."""
    if not token:
        return False
    if cache.touch(_chave(token), timeout=segundos):
        return True
    # Esquecido pelo Redis, mas fixado na conversa: volta do armazém.
    return _do_armazem(token) is not None


def descartar(token: str) -> None:
    if token:
        cache.delete(_chave(token))
