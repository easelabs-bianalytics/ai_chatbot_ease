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
# Até quantas casas o arredondamento é conferido. A resposta pode copiar
# 0,0659568115 de um 0,06595681152099932 (Racional Metas, 2026-10-01): é o
# mesmo número com menos casas, não um número novo.
_MAX_CASAS_DECIMAIS = 12
# "1." "2." "3." no começo de um passo a passo: é a numeração da lista, não
# dado. Contá-la derrubou a explicação certa da meta do Hermes (2026-10-01).
_MARCADOR_DE_LISTA = re.compile(r"(?m)^[ \t]*(?:[-*][ \t]+)?\d{1,2}[.)][ \t]")
# Separador de milhar no padrão brasileiro: "8.635", "12.128.301".
_MILHAR = re.compile(r"^\d{1,3}(?:\.\d{3})+(?:,\d+)?$")
_MAT = re.compile(r"\bMAT\b", re.I)
_DOSE_NO_NOME = re.compile(r"(\d+)\s*(?:ml|mg)\b", re.I)

# Número que é RÓTULO, não dado: só vale colado à palavra que o define.
# "equipes 1, 2 e 4", "setor 3000", "Base 660", "Isolado 100 mg/mL",
# "Categoria 2", "2º trimestre" nomeiam coisas documentadas nas referências;
# não são quantidades que a resposta precisasse tirar do banco. Em 2026-10-08
# (conversa 67) duas explicações corretas de como o Jarvis separa FV e Digital
# viraram o texto de reserva só por citarem "equipes 1, 2 e 4", e um gráfico
# trimestral perdeu a narrativa por dizer "2º trimestre". Um "2" solto
# continua precisando de fonte.
_ROTULOS = (
    re.compile(r"\bequipes?\s+\d{1,2}(?:\s*(?:,|e|ou)\s*\d{1,2})*", re.I),
    re.compile(r"\bsetor(?:es)?\s+\d{3,4}(?:\s*(?:,|e|ou)\s*\d{3,4})*", re.I),
    re.compile(r"\bBase\s+660\b", re.I),
    re.compile(r"\b\d+(?:[.,]\d+)?\s*mg\s*/\s*ml\b", re.I),
    re.compile(r"\b\d+\s*ml\b", re.I),
    re.compile(r"\bcategorias?\s+[1-5](?:\s*(?:,|e|a|ou)\s*[1-5])*\b", re.I),
    re.compile(r"\b\d{1,2}\s*[ºª°]"),
    re.compile(r"\b\d{1,2}\s*(?:º|ª|°)?\s*(?:tri|trimestre|semestre|quadrimestre)\b", re.I),
)


def sem_rotulos(texto: str) -> str:
    """O texto sem os números que são rótulo (ver `_ROTULOS`)."""
    for padrao in _ROTULOS:
        texto = padrao.sub(" ", texto or "")
    return texto


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


def _casas_de(token: str, candidato: float) -> int:
    """Casas decimais do token NA LEITURA que deu este candidato. "8.635"
    lido como oito mil seiscentos e trinta e cinco não tem casa nenhuma:
    contar três fazia o arredondamento de 8634,52 não valer."""
    token = token.strip().rstrip(".,")
    if _MILHAR.match(token) and candidato == float(token.replace(".", "").replace(",", ".")):
        return len(token.split(",", 1)[1]) if "," in token else 0
    return _casas_decimais(token)


def numeros_do_texto(texto: str) -> list:
    """[(token, candidatos)] de tudo que parece número no texto."""
    return [(t, _candidatos(t)) for t in _NUMERO.findall(_MARCADOR_DE_LISTA.sub("", texto or ""))]


# "28,6 mil unidades", "12,1 milhões": o número dito em escala.
_ESCALAS = (
    (re.compile(r"^\s?(?:mil)\b", re.I), 1_000),
    (re.compile(r"^\s?(?:milh[õo]es|milh[ãa]o|mi)\b", re.I), 1_000_000),
    (re.compile(r"^\s?(?:bilh[õo]es|bilh[ãa]o|bi)\b", re.I), 1_000_000_000),
)


def _escalas(texto: str) -> dict:
    """{token: fator} dos números ditos em escala ("28,6 mil" → 1.000)."""
    texto = _MARCADOR_DE_LISTA.sub("", texto or "")
    escalas = {}
    for m in _NUMERO.finditer(texto):
        depois = texto[m.end():m.end() + 12]
        for padrao, fator in _ESCALAS:
            if padrao.match(depois):
                escalas[m.group(0)] = fator
                break
    return escalas


def _percentuais(texto: str) -> set:
    """Os tokens escritos como percentual ("6,60%", "13,4 %")."""
    texto = _MARCADOR_DE_LISTA.sub("", texto or "")
    return {m.group(0) for m in _NUMERO.finditer(texto) if re.match(r"\s?%", texto[m.end():m.end() + 2])}


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

    # MAT é, por definição, 12 meses: "o MAT de set/2025 a ago/2026, os 12
    # meses fechados" não inventa o 12. Só quando a pergunta ou a conversa
    # fala em MAT — fora disso, 12 continua precisando de fonte.
    if _MAT.search(question or ""):
        suportados.add(12.0)

    # Competência em AAAAMM ("202509", o `cod_anomes` do mercado): a resposta
    # escreve "set/2025", e o 2025 e o 9 são o mesmo dado dito por extenso.
    # Sem isto, em 2026-09-23 duas respostas certas de mercado ("de set/2025 a
    # ago/2026") viraram tabela crua: o período veio do MAX da base, então o
    # ano não estava em filtro nenhum. Só o que tem cara de competência — ano
    # de 2000 a 2099 e mês de 1 a 12 —, para um SKU como 259434 não virar ano.
    for n in list(suportados):
        if n.is_integer() and 200001 <= n <= 209912 and 1 <= int(n) % 100 <= 12:
            suportados |= {float(int(n) // 100), float(int(n) % 100)}

    # O texto não carrega o sinal: "caiu 61 unidades" e "recuou 13,4%" citam
    # o -61 e o -13,4 do resultado, e a expressão que acha números no texto
    # nunca pega o "-". Sem isto, em 2026-09-21 uma análise correta ("não
    # caiu: subiu 6,7%, puxada pelo CDD; os demais recuaram") foi reprovada
    # duas vezes e virou tabela crua. O valor absoluto não inventa número:
    # é o mesmo dado, dito com palavra em vez de sinal.
    suportados |= {abs(n) for n in suportados}
    return suportados


def _tem_suporte(token: str, candidatos: set, suportados: set, percentual: bool = False, escala: int = 1) -> bool:
    if percentual:
        # Participação gravada como fração (0,0659) e dita como percentual
        # (6,60%): é o mesmo dado em outra unidade, não conta nova.
        suportados = suportados | {s * 100 for s in suportados if abs(s) <= 10}
    if escala != 1:
        # "28,6 mil" a partir de 28.606,8: o mesmo número, dito em escala.
        suportados = suportados | {s / escala for s in suportados if abs(s) >= escala}
    for candidato in candidatos:
        if candidato in suportados:
            return True
        casas = min(_casas_de(token, candidato), _MAX_CASAS_DECIMAIS)
        for suportado in suportados:
            # A resposta pode arredondar o que veio do banco (1,3512 → 1,35;
            # 8634,52 → 8.635), mas não inventar.
            if round(suportado, casas) == candidato:
                return True
    return False


def _sem_suporte(reply: str, suportados: set) -> tuple:
    reply = sem_rotulos(reply)
    percentuais = _percentuais(reply)
    escalas = _escalas(reply)
    return tuple(
        token
        for token, candidatos in numeros_do_texto(reply)
        if candidatos and not _tem_suporte(token, candidatos, suportados, token in percentuais, escalas.get(token, 1))
    )


def check_grounding_varias(reply: str, consultas, question: str) -> GroundingResult:
    """A mesma regra, para a análise que cruza várias consultas (ADR-0025).

    `consultas` é uma sequência de (columns, rows, sql, row_count). Um número
    vale se estiver em QUALQUER uma delas — a análise de uma queda cita o
    total de uma consulta, a regional de outra e o concorrente de uma
    terceira. Continua proibido citar o que nenhuma trouxe."""
    suportados = set()
    for columns, rows, sql, row_count in consultas:
        suportados |= numeros_suportados(columns, rows, question, sql, row_count)

    sem_suporte = _sem_suporte(reply, suportados)
    return GroundingResult(ok=not sem_suporte, unsupported=sem_suporte)


def check_grounding(reply: str, columns, rows, question: str, sql: str, row_count=None) -> GroundingResult:
    suportados = numeros_suportados(columns, rows, question, sql, row_count)

    sem_suporte = _sem_suporte(reply, suportados)
    return GroundingResult(ok=not sem_suporte, unsupported=sem_suporte)
