"""Autocrítica do seguimento: o pedido de mudança mudou alguma coisa?

Na conversa 15 (2026-09-23), "considere Extras, MP, SS e Voucher também" voltou
com o mesmo 4.306 × 4.716 da resposta anterior, e a redação escreveu que tinha
considerado tudo. Nenhuma regra específica pegaria isso a tempo; uma
conferência genérica pega: **se o planejador disse que o seguimento muda o
dado e o resultado saiu idêntico ao da resposta anterior, o pedido não foi
atendido.** O planejador ganha uma segunda chance, com esse aviso.

É conferência determinística e de custo zero: compara números, não texto.
Nome de coluna não conta — trocar `vendas` por `vendas_total` e devolver os
mesmos valores é exatamente o erro que se quer pegar.
"""

from dataclasses import dataclass

# O que o planejador diz do seguimento (campo `seguimento` do plano).
MUDA_O_DADO = "muda_o_dado"

CASAS = 6


@dataclass(frozen=True)
class Anterior:
    """A consulta que sustentou a resposta anterior."""

    colunas: tuple
    linhas: tuple
    row_count: int
    sql: str


def _numeros(linha) -> tuple:
    return tuple(sorted(
        round(float(v), CASAS) for v in linha
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ))


def mesmo_resultado(resultado, anterior: Anterior | None) -> bool:
    """O resultado novo repete os números do anterior, linha a linha.

    A amostra guardada da anterior pode ter só as primeiras linhas; compara
    as que existem dos dois lados, e exige o mesmo total de linhas."""
    if anterior is None or not anterior.linhas or not resultado.rows:
        return False
    if (anterior.row_count or len(anterior.linhas)) != resultado.row_count:
        return False
    pares = list(zip(anterior.linhas, resultado.rows))
    numeros = [(_numeros(a), _numeros(b)) for a, b in pares]
    if not any(a for a, _ in numeros):
        return False            # sem número não há o que comparar
    return all(a == b for a, b in numeros)


def nota(entendimento: str, anterior: Anterior) -> str:
    """O aviso que vai ao planejador na segunda chance."""
    return (
        "A consulta que você escreveu devolveu exatamente os mesmos números da resposta "
        f"anterior ({anterior.row_count} linhas, mesmos valores). Você marcou este seguimento "
        "como mudança de dado"
        + (f", entendido como: {entendimento}" if entendimento else "")
        + ". Então o pedido não foi atendido. Releia o pedido e a consulta anterior e "
        "reescreva a consulta para fazer a mudança (incluir, tirar, trocar fonte, período, "
        "recorte ou medida). Se a mudança não altera o resultado de verdade (a fonte incluída "
        "está zerada, o recorte já era esse), mantenha a consulta e explique isso em "
        "`pedido_nao_atendido`, com o motivo."
    )


NAO_MUDOU = (
    "a consulta refeita devolveu os mesmos números da resposta anterior; diga isso logo no "
    "começo e explique por que o pedido não mudou o resultado"
)
