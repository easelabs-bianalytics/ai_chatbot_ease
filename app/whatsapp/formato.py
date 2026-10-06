"""Texto do Jarvis no jeito do WhatsApp (ADR-0028).

A redação escreve Markdown para o chat web. O WhatsApp tem a sua própria
marcação — `*negrito*`, `_itálico_`, `~riscado~`, ``` `código` ``` — e não
desenha tabela nem título. Aqui a mesma resposta ganha a forma que o celular
lê, sem mudar uma palavra nem um número.
"""

import re

from ai_orchestrator.orchestrator import formatar_valor

# Uma tela de celular mostra ~34 caracteres de fonte monoespaçada por linha.
# Tabela mais larga que isso quebra e fica ilegível: vira lista.
LARGURA_DO_CELULAR = 34
MAX_LINHAS_NA_TABELA = 12
# O WhatsApp aceita mensagens bem maiores, mas acima disto ninguém lê de uma
# vez: a resposta sai em partes, cortadas em parágrafo.
MAX_CARACTERES_POR_MENSAGEM = 3500


def de_markdown(texto: str) -> str:
    linhas = []
    for linha in (texto or "").splitlines():
        linha = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", linha)
        # `*assim*` no Markdown é itálico, e a tela mostra itálico; no
        # WhatsApp seria negrito (2026-10-06). A mesma regra do app.js.
        linha = re.sub(r"(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)", r"\1_\2_", linha)
        titulo = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", linha)
        if titulo:
            linha = f"*{titulo.group(1).strip().strip('*')}*"
        linhas.append(linha)
    texto = "\n".join(linhas)
    texto = _tabelas_markdown(texto)
    texto = re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto)
    texto = re.sub(r"__(.+?)__", r"*\1*", texto)
    texto = re.sub(r"~~(.+?)~~", r"~\1~", texto)
    texto = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _tabelas_markdown(texto: str) -> str:
    """Tabela em Markdown (`| a | b |`) dentro do texto vira a mesma tabela
    das respostas em blocos: monoespaçada se couber no celular, senão uma
    linha por registro. A redação é orientada a não escrever tabela no texto,
    mas às vezes escreve."""
    saida, bloco = [], []

    def fechar():
        if bloco:
            saida.append(tabela_de_texto(bloco))
            bloco.clear()

    for linha in texto.split("\n"):
        if linha.count("|") >= 2:
            bloco.append(linha)
        else:
            fechar()
            saida.append(linha)
    fechar()
    return "\n".join(saida)


def tabela_crua(texto: str) -> str:
    """A saída de segurança do orquestrador (ADR-0010) no jeito do celular.

    Quando a redação é reprovada duas vezes na ancoragem, a resposta é o
    resultado em texto: cabeçalho e linhas separados por " | ", e talvez um
    parágrafo de rodapé ("Mostrando as 20 primeiras..."). Em 2026-10-06 isso
    chegou ao WhatsApp como um bloco monoespaçado de nove colunas, quebrado
    no meio das linhas e ilegível. A tela já desenhava a tabela; aqui ela
    ganha a mesma forma das outras tabelas do WhatsApp."""
    tabela_texto, _, rodape = (texto or "").strip().partition("\n\n")
    linhas = [l for l in tabela_texto.splitlines() if l.strip()]
    if len(linhas) < 2 or not all("|" in l for l in linhas):
        return de_markdown(texto)
    rodape = rodape.strip().strip("()")
    return (tabela_de_texto(linhas) + (f"\n\n_{rodape}_" if rodape else "")).strip()


def tabela_de_texto(linhas) -> str:
    """Linhas já formatadas, células separadas por "|" (a primeira é o
    cabeçalho; a linha de traços do Markdown é ignorada)."""
    linhas = [l for l in linhas if not re.match(r"^\s*\|?\s*:?-{2,}", l)]
    # O negrito do Markdown dentro da célula: no bloco monoespaçado os
    # asteriscos apareceriam crus.
    celulas = [[c.strip().replace("**", "") for c in l.strip().strip("|").split("|")] for l in linhas]
    cabecalho, *corpo = celulas
    largura = len(cabecalho)
    corpo = [(l + [""] * largura)[:largura] for l in corpo[:MAX_LINHAS_NA_TABELA]]
    return _desenhar([re.sub(r"_+", " ", c) for c in cabecalho], corpo)


def tabela(colunas, linhas) -> str:
    """Resultado curto, legível no celular: bloco monoespaçado se couber na
    largura, senão uma linha por registro."""
    colunas = list(colunas)
    celulas = [[formatar_valor(v, c) for v, c in zip(linha, colunas)] for linha in linhas[:MAX_LINHAS_NA_TABELA]]
    return _desenhar([re.sub(r"_+", " ", c) for c in colunas], celulas)


def _desenhar(rotulos, celulas) -> str:
    """Bloco monoespaçado se couber na largura do celular; senão um registro
    por vez, que nunca quebra no meio de uma coluna."""
    celulas = [[_data(v) for v in linha] for linha in celulas]
    larguras = [max([len(r)] + [len(l[i]) for l in celulas]) for i, r in enumerate(rotulos)]
    numericas = [all(re.fullmatch(r"-?[\d.,]+%?", l[i] or "0") for l in celulas) for i in range(len(rotulos))]

    if sum(larguras) + 2 * (len(rotulos) - 1) <= LARGURA_DO_CELULAR:
        def formatar(valores):
            return "  ".join(v.rjust(w) if n else v.ljust(w) for v, w, n in zip(valores, larguras, numericas)).rstrip()

        corpo = [formatar(rotulos), formatar(["-" * w for w in larguras])] + [formatar(l) for l in celulas]
        return "```\n" + "\n".join(corpo) + "\n```"

    registros = []
    for linha in celulas:
        primeiro, *resto = linha
        pares = [f"{r}: {v}" for r, v in zip(rotulos[1:], resto) if v != ""]
        if len(rotulos) > 4:
            # Muitas colunas numa linha só viram um parágrafo que ninguém lê
            # (2026-10-06): uma por linha, abaixo do registro.
            registros.append(f"*{primeiro}*\n" + "\n".join(f"  {p}" for p in pares))
        else:
            registros.append(f"• *{primeiro}*" + (f" — {' · '.join(pares)}" if pares else ""))
    return ("\n\n" if any("\n" in r for r in registros) else "\n").join(registros)


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?")


def _data(valor: str) -> str:
    """Data do banco em ISO ("2026-04-01", "2026-10-01T15:46:41-03:00") no
    formato de quem lê, como a tabela da tela (`fmtCelula`, app.js)."""
    iso = _ISO.match(valor or "")
    if not iso or len(valor) > 35:
        return valor
    data = f"{iso[3]}/{iso[2]}/{iso[1]}"
    return f"{data} {iso[4]}:{iso[5]}" if iso[4] else data


def dividir(texto: str) -> list:
    """Em partes de até MAX_CARACTERES_POR_MENSAGEM, cortadas em parágrafo."""
    if len(texto) <= MAX_CARACTERES_POR_MENSAGEM:
        return [texto] if texto else []
    partes, atual = [], ""
    for paragrafo in texto.split("\n\n"):
        candidato = f"{atual}\n\n{paragrafo}" if atual else paragrafo
        if len(candidato) <= MAX_CARACTERES_POR_MENSAGEM:
            atual = candidato
            continue
        if atual:
            partes.append(atual)
        while len(paragrafo) > MAX_CARACTERES_POR_MENSAGEM:
            partes.append(paragrafo[:MAX_CARACTERES_POR_MENSAGEM])
            paragrafo = paragrafo[MAX_CARACTERES_POR_MENSAGEM:]
        atual = paragrafo
    if atual:
        partes.append(atual)
    return partes
