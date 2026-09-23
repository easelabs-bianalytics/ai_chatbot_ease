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
        titulo = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", linha)
        if titulo:
            linha = f"*{titulo.group(1).strip().strip('*')}*"
        linha = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", linha)
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
    """Tabela em Markdown (`| a | b |`) dentro do texto vira bloco
    monoespaçado. A redação é orientada a não escrever tabela no texto, mas a
    saída de segurança (tabela crua, ADR-0010) escreve."""
    saida, bloco = [], []

    def fechar():
        if bloco:
            corpo = [l for l in bloco if not re.match(r"^\s*\|?\s*:?-{2,}", l)]
            saida.append("```\n" + "\n".join(l.strip().strip("|").replace("|", " | ").strip() for l in corpo) + "\n```")
            bloco.clear()

    for linha in texto.split("\n"):
        if linha.count("|") >= 2:
            bloco.append(linha)
        else:
            fechar()
            saida.append(linha)
    fechar()
    return "\n".join(saida)


def tabela(colunas, linhas) -> str:
    """Resultado curto, legível no celular: bloco monoespaçado se couber na
    largura, senão uma linha por registro."""
    colunas = list(colunas)
    celulas = [[formatar_valor(v, c) for v, c in zip(linha, colunas)] for linha in linhas[:MAX_LINHAS_NA_TABELA]]
    rotulos = [re.sub(r"_+", " ", c) for c in colunas]
    larguras = [max([len(r)] + [len(l[i]) for l in celulas]) for i, r in enumerate(rotulos)]
    numericas = [all(re.fullmatch(r"-?[\d.,]+%?", l[i] or "0") for l in celulas) for i in range(len(colunas))]

    if sum(larguras) + 2 * (len(colunas) - 1) <= LARGURA_DO_CELULAR:
        def formatar(valores):
            return "  ".join(v.rjust(w) if n else v.ljust(w) for v, w, n in zip(valores, larguras, numericas)).rstrip()

        corpo = [formatar(rotulos), formatar(["-" * w for w in larguras])] + [formatar(l) for l in celulas]
        return "```\n" + "\n".join(corpo) + "\n```"

    registros = []
    for linha in celulas:
        primeiro, *resto = linha
        detalhes = " · ".join(f"{r}: {v}" for r, v in zip(rotulos[1:], resto) if v != "")
        registros.append(f"• *{primeiro}*" + (f" — {detalhes}" if detalhes else ""))
    return "\n".join(registros)


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
