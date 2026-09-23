"""O que o Jarvis está fazendo agora, para a tela mostrar (ADR-0025).

Uma resposta leva de 10 s a três minutos. "Pensando…" parado esse tempo todo
parece travamento. Aqui fica o estado da pergunta, que o polling da tela lê
junto com a pergunta pendente:

- `etapa`: entendi → consultando → escrevendo (e investigando, conferindo);
- `texto`: a frase curta da etapa ("Testando: a queda foi concentrada?");
- `entendimento`: a pergunta como o planejador a entendeu. Mostrado enquanto
  a resposta não chega, é o jeito mais barato de evitar erro: a pessoa vê
  "Entendi: vendas 1–20/09 × 1–20/08, só CDD" e para antes de ler a resposta
  errada.

Mora no cache (o Redis da task), com prazo: é estado de passagem, não
registro. O registro de verdade é a auditoria da resposta.
"""

from django.core.cache import cache

SEGUNDOS = 10 * 60
MAX_CARACTERES = 160
MAX_ENTENDIMENTO = 400
ETAPAS = frozenset({"entendi", "consultando", "escrevendo", "investigando", "conferindo"})


def _chave(message_id: int) -> str:
    return f"progresso:{message_id}"


def _curto(texto, limite: int) -> str:
    return " ".join(str(texto or "").split())[:limite]


def definir(message_id: int, texto: str, etapa: str = "investigando", entendimento: str = "") -> None:
    """Falha aqui nunca derruba a resposta: progresso é cortesia."""
    try:
        atual = ler_tudo(message_id)
        estado = {
            "texto": _curto(texto, MAX_CARACTERES),
            "etapa": etapa if etapa in ETAPAS else "investigando",
            # O entendimento dito uma vez continua na tela nas etapas seguintes.
            "entendimento": _curto(entendimento, MAX_ENTENDIMENTO) or atual.get("entendimento", ""),
        }
        cache.set(_chave(message_id), estado, timeout=SEGUNDOS)
    except Exception:  # noqa: BLE001 — cache fora do ar não pode parar a resposta
        pass


def ler_tudo(message_id: int) -> dict:
    try:
        valor = cache.get(_chave(message_id)) or {}
    except Exception:  # noqa: BLE001
        return {}
    if isinstance(valor, str):
        return {"texto": valor, "etapa": "investigando", "entendimento": ""}
    return dict(valor)


def ler(message_id: int) -> str:
    """Só a frase da etapa."""
    return ler_tudo(message_id).get("texto", "")


def limpar(message_id: int) -> None:
    try:
        cache.delete(_chave(message_id))
    except Exception:  # noqa: BLE001
        pass
