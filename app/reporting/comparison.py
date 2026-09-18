"""Compara o resultado da consulta da IA com o do gabarito.

A IA pode dar outro nome às colunas, trocar a ordem delas ou trazer uma
coluna a mais (o total junto do share, por exemplo) e continuar certa. O
que não pode mudar são os números. Por isso a comparação é por coluna: cada
coluna do gabarito precisa ter uma coluna na resposta da IA com exatamente
os mesmos valores (como conjunto com repetição), e as duas precisam ter o
mesmo número de linhas.
"""

import datetime
import decimal
from collections import Counter
from dataclasses import dataclass

CASAS = 2


def _valor(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, decimal.Decimal)):
        # 12 e 12.0 são o mesmo número; 12.004 e 12.00 também, no
        # arredondamento que a resposta mostraria.
        return round(float(v), CASAS) + 0.0
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()[:10]
    texto = str(v).strip()
    # Número guardado como texto ('202608', '25.00') compara como número: a
    # IA pode ter feito o cast que a referência não fez.
    try:
        return round(float(texto), CASAS) + 0.0
    except ValueError:
        return texto.upper()


def _colunas(resultado) -> list:
    return [
        Counter(_valor(linha[i]) for linha in resultado.rows)
        for i in range(len(resultado.columns))
    ]


@dataclass(frozen=True)
class Comparacao:
    igual: bool
    motivo: str = ""


def comparar(gabarito, obtido, colunas=()) -> Comparacao:
    """`colunas` limita a comparação às colunas do gabarito que respondem a
    pergunta; vazio compara todas."""
    if gabarito.truncated or obtido.truncated:
        return Comparacao(False, "resultado cortado no limite de linhas; conferir à mão")
    if gabarito.row_count != obtido.row_count:
        return Comparacao(
            False,
            f"{obtido.row_count} linhas na resposta da IA e {gabarito.row_count} no gabarito",
        )

    disponiveis = _colunas(obtido)
    alvo = {c.lower() for c in colunas}
    faltando = []
    for nome, coluna in zip(gabarito.columns, _colunas(gabarito)):
        if alvo and nome.lower() not in alvo:
            continue
        if coluna in disponiveis:
            disponiveis.remove(coluna)
        else:
            faltando.append(nome)

    if faltando:
        return Comparacao(
            False, f"valores diferentes do gabarito nas colunas: {', '.join(faltando)}"
        )
    return Comparacao(True)
