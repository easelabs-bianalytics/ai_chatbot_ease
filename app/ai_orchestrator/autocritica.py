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

import re
import unicodedata
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


# --------------------------------------------------- crítica da resposta

# Na conversa 22 (2026-09-24), "Veja o visual que criou, que coisa feia!!",
# com o print, voltou com o Jarvis concordando e descrevendo o que refaria, e
# só "Faça então amigo!! por favor" trouxe o gráfico corrigido. Crítica à
# resposta anterior é pedido de correção: a versão corrigida sai na hora.
# Mensagem longa é pergunta nova, mesmo com uma dessas palavras no meio.
MAX_LETRAS_DA_CRITICA = 240

_CRITICA = re.compile(
    r"\b(?:feio|feia|horrivel|pessim[oa]|ruim|mal feito|poluid[oa]|ilegive(?:l|is)|sobrepost\w*"
    r"|errad[oa]s?|incorret[oa]s?|nao (?:ficou|gostei|e isso|era isso|esta certo|bate|funcionou"
    r"|apareceu|veio|fez|faz sentido|ta bom|esta bom)|faltou|esqueceu"
    r"|corrij\w*|corrig\w*|consert\w*|arrum\w*|refa(?:ca|z|zer)|melhore|melhora (?:isso|o|a|esse|essa))\b"
)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", (texto or "").lower())
    return " ".join("".join(c for c in sem_acento if unicodedata.category(c) != "Mn").split())


def e_critica(mensagem: str) -> bool:
    """A mensagem reclama da resposta anterior ou pede que ela seja corrigida."""
    texto = _normalizar(mensagem)
    return bool(texto) and len(texto) <= MAX_LETRAS_DA_CRITICA and bool(_CRITICA.search(texto))


NOTA_DA_CRITICA = (
    "A pessoa criticou a sua resposta anterior (o número, a tabela, o gráfico ou o texto). "
    "Releia o histórico e a consulta que a sustentou, descubra o que ficou errado — "
    "confira a consulta, o período (mês parcial entrou onde não devia?), o formato do "
    "resultado e o desenho do gráfico — e **entregue agora a versão corrigida**: "
    "`answer_with_data`, com a consulta e o gráfico refeitos. Não responda só "
    "reconhecendo o erro nem dizendo o que vai fazer: a pessoa não deveria precisar pedir "
    "de novo. Se a mensagem não for uma crítica à resposta anterior, e sim uma pergunta "
    "nova, ignore este aviso."
)

