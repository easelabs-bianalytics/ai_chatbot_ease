"""Checagem de ancoragem numérica (ADR-0010).

Todo número que sai na resposta precisa existir no resultado da consulta, na
pergunta ou num filtro do SQL. É a última barreira antes do envio: o modelo
arredonda, soma e completa com plausibilidade, e um número inventado numa
resposta de BI é pior do que não ter resposta.

Literal da lista do SELECT não conta de propósito — senão bastaria o modelo
escrever o número que quisesse dentro da própria consulta para "ancorá-lo".
"""

import re
from dataclasses import dataclass
from datetime import date

import sqlglot
from sqlglot import exp

_NUMERO = re.compile(r"\d[\d.,]*\d|\d")
_MAX_CASAS_DECIMAIS = 6
_DOSE_NO_NOME = re.compile(r"(\d+)\s*(?:ml|mg)\b", re.I)


@dataclass(frozen=True)
class GroundingResult:
    ok: bool
    unsupported: tuple = ()

    @property
    def reason(self) -> str:
        if self.ok:
            return ""
        numeros = ", ".join(str(n) for n in self.unsupported)
        return (
            f"a resposta cita número que não está no resultado da consulta: "
            f"{numeros}. Use apenas os valores que voltaram do banco, sem "
            "calcular nem arredondar por conta própria."
        )


def _candidatos(token: str) -> set:
    """Interpretações possíveis de um número escrito em texto.

    "1.234,5" é pt-BR; "1,234.5" é inglês; "12.345" pode ser qualquer um dos
    dois. Na dúvida aceitamos as duas leituras: barrar uma resposta correta
    por ambiguidade de separador seria pior do que deixar passar um caso
    raro."""
    token = token.strip().rstrip(".,")
    if not token:
        return set()

    valores = set()
    for limpo in {token.replace(".", "").replace(",", "."), token.replace(",", "")}:
        try:
            valores.add(float(limpo))
        except ValueError:
            continue
    return valores


def _casas_decimais(token: str) -> int:
    separador = max(token.rfind(","), token.rfind("."))
    if separador == -1:
        return 0
    return len(token) - separador - 1


def numeros_do_texto(texto: str) -> list:
    """[(token, candidatos)] de tudo que parece número no texto."""
    return [(t, _candidatos(t)) for t in _NUMERO.findall(texto or "")]


def _numeros_de(valor) -> set:
    if isinstance(valor, bool) or valor is None:
        return set()
    if isinstance(valor, (int, float)):
        return {float(valor)}
    # Texto (SKU, EAN, CNPJ, data em ISO): os números dentro dele também
    # sustentam a resposta.
    return {v for t, cs in numeros_do_texto(str(valor)) for v in cs}


def _literais_de_filtro(sql: str) -> set:
    """Números que aparecem em WHERE, HAVING e JOIN ... ON.

    São os valores que a pergunta trouxe (período, código, limite), e a
    resposta costuma repeti-los."""
    try:
        arvore = sqlglot.parse_one(sql or "", read="postgres")
    except sqlglot.ParseError:
        return set()

    numeros = set()
    for clausula in list(arvore.find_all(exp.Where)) + list(arvore.find_all(exp.Having)):
        for literal in clausula.find_all(exp.Literal):
            numeros |= _numeros_de(literal.this)
    return numeros


def numeros_suportados(columns, rows, question: str, sql: str, row_count=None) -> set:
    suportados = set()
    for linha in rows:
        for valor in linha:
            suportados |= _numeros_de(valor)

    for _, candidatos in numeros_do_texto(question):
        suportados |= candidatos

    suportados |= _literais_de_filtro(sql)

    # A quantidade de linhas é fato do resultado: "são 3 SKUs" não é invenção.
    suportados.add(float(len(rows) if row_count is None else row_count))

    # A data de hoje vai no contexto ("Hoje: 21/09/2026") justamente para a
    # resposta poder dizer que uma foto é de 27/08, não de hoje. Citá-la não é
    # inventar número — e reprová-la derrubou a resposta do estoque da Raia.
    hoje = date.today()
    suportados |= {float(hoje.day), float(hoje.month), float(hoje.year)}

    # Dose e volume que estão no NOME da coluna ("isolado_30ml",
    # "cbd_20mg"): o texto diz "Isolado 30 mL". Só com a unidade colada — um
    # número solto num apelido de coluna continua não valendo, senão bastaria
    # o modelo escrever "AS total_4500" para ancorar o que quisesse.
    for coluna in columns or ():
        for numero in _DOSE_NO_NOME.findall(str(coluna)):
            suportados.add(float(numero))

    # O texto não carrega o sinal: "caiu 61 unidades" e "recuou 13,4%" citam
    # o -61 e o -13,4 do resultado, e a expressão que acha números no texto
    # nunca pega o "-". Sem isto, em 2026-09-21 uma análise correta ("não
    # caiu: subiu 6,7%, puxada pelo CDD; os demais recuaram") foi reprovada
    # duas vezes e virou tabela crua. O valor absoluto não inventa número:
    # é o mesmo dado, dito com palavra em vez de sinal.
    suportados |= {abs(n) for n in suportados}
    return suportados


def _tem_suporte(token: str, candidatos: set, suportados: set) -> bool:
    casas = _casas_decimais(token)
    for candidato in candidatos:
        if candidato in suportados:
            return True
        for suportado in suportados:
            # A resposta pode arredondar o que veio do banco (1,3512 → 1,35),
            # mas não inventar.
            if round(suportado, min(casas, _MAX_CASAS_DECIMAIS)) == candidato:
                return True
    return False


def check_grounding_varias(reply: str, consultas, question: str) -> GroundingResult:
    """A mesma regra, para a análise que cruza várias consultas (ADR-0025).

    `consultas` é uma sequência de (columns, rows, sql, row_count). Um número
    vale se estiver em QUALQUER uma delas — a análise de uma queda cita o
    total de uma consulta, a regional de outra e o concorrente de uma
    terceira. Continua proibido citar o que nenhuma trouxe."""
    suportados = set()
    for columns, rows, sql, row_count in consultas:
        suportados |= numeros_suportados(columns, rows, question, sql, row_count)

    sem_suporte = tuple(
        token
        for token, candidatos in numeros_do_texto(reply)
        if candidatos and not _tem_suporte(token, candidatos, suportados)
    )
    return GroundingResult(ok=not sem_suporte, unsupported=sem_suporte)


def check_grounding(reply: str, columns, rows, question: str, sql: str, row_count=None) -> GroundingResult:
    suportados = numeros_suportados(columns, rows, question, sql, row_count)

    sem_suporte = tuple(
        token
        for token, candidatos in numeros_do_texto(reply)
        if candidatos and not _tem_suporte(token, candidatos, suportados)
    )
    return GroundingResult(ok=not sem_suporte, unsupported=sem_suporte)
