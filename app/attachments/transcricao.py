"""O print como dado: transcrição em blocos, junção dos pedaços e conferência
(motor 3.0 dos prints, ADR-0035).

O leitor de imagem transcreve cada bloco de dado do print — tabela, lista,
série de um gráfico, cartões de indicador. Aqui, sem modelo:

- os pedaços de um print longo viram um bloco só (`juntar`), sem repetir a
  linha que caiu na sobreposição;
- a transcrição é conferida (`conferir`): largura das linhas, número escrito
  no formato brasileiro, linha de total que fecha ou não com a soma, célula
  que o leitor marcou como ilegível;
- os blocos viram uma planilha em memória (`montar_planilha`), uma aba por
  bloco — e daí o print é `anexo.<aba>` na consulta, como a planilha do
  ADR-0031: cruza com o banco, e a conta é do SQL.

O resumo da conferência vai para o planejador e para a pessoa: transcrição é
leitura de imagem, e quem a usa precisa saber o que ficou de fora.
"""

import io
import re
from dataclasses import dataclass, field

from attachments.limites import MAX_COLUNAS, AnexoRecusado
from attachments.planilha import INICIOS_DE_FORMULA, normalizar

# Linhas por bloco. A lista de 230 CRMs cabe folgada; acima disso o print
# não é o jeito de mandar o dado, e a resposta diz isso.
MAX_LINHAS_POR_BLOCO = 2_000
# Linhas comparadas na emenda de dois pedaços (a sobreposição tem ~48 px:
# uma ou duas linhas de tabela).
LINHAS_NA_EMENDA = 3
# Diferença tolerada entre a linha de total e a soma: arredondamento do que
# o print mostra (0,5%).
TOLERANCIA_DO_TOTAL = 0.005

TIPOS = ("tabela", "lista", "grafico", "indicadores")
_ILEGIVEL = re.compile(r"^\s*(?:\?+|\[?ileg[ií]vel\]?)\s*$", re.I)
_TOTAL = re.compile(r"^\s*(?:total|soma|subtotal)\b", re.I)


@dataclass(frozen=True)
class Bloco:
    tipo: str
    titulo: str
    colunas: tuple
    linhas: tuple          # tuplas de valores: texto, número (float) ou None

    @property
    def aba(self) -> str:
        return self.titulo


@dataclass
class Transcricao:
    blocos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    pedacos: int = 1

    @property
    def linhas(self) -> int:
        return sum(len(b.linhas) for b in self.blocos)

    def resumo(self) -> str:
        """Uma frase por bloco e os avisos: o que a pessoa e o planejador leem."""
        if not self.blocos:
            return ""
        partes = []
        for bloco in self.blocos:
            colunas = ", ".join(str(c) for c in bloco.colunas[:8]) + ("…" if len(bloco.colunas) > 8 else "")
            partes.append(f"`{bloco.titulo}` ({_NOMES[bloco.tipo]}): {len(bloco.linhas)} linhas, colunas {colunas}")
        texto = "Transcrevi do print " + "; ".join(partes) + "."
        if self.pedacos > 1:
            texto += f" O print foi lido em {self.pedacos} pedaços."
        if self.avisos:
            texto += " " + " ".join(self.avisos)
        return texto


_NOMES = {"tabela": "tabela", "lista": "lista", "grafico": "valores do gráfico", "indicadores": "indicadores"}


# ------------------------------------------------------------ junção


def juntar(leituras, direcao: str) -> tuple:
    """Os blocos de vários pedaços do mesmo print, em `(blocos, avisos)`.

    Vertical (lista alta): o bloco do pedaço seguinte continua o último bloco
    com o mesmo número de colunas; a linha repetida na emenda sai.
    Horizontal (faixa larga): as colunas do pedaço seguinte entram ao lado,
    linha a linha — só quando o número de linhas bate; senão fica o primeiro
    pedaço e o aviso diz que as colunas não alinharam."""
    leituras = [list(l) for l in leituras]
    if not leituras:
        return [], []
    blocos = [_copia(b) for b in leituras[0]]
    avisos = []
    for seguinte in leituras[1:]:
        for bloco in seguinte:
            alvo = _alvo(blocos, bloco, direcao)
            if alvo is None:
                blocos.append(_copia(bloco))
            elif direcao == "horizontal":
                if not _ao_lado(alvo, bloco):
                    avisos.append(
                        f"As colunas da direita do print não alinharam com as da esquerda "
                        f"({len(getattr(bloco, 'linhas', ()))} linhas contra {len(alvo['linhas'])}); usei só a parte da esquerda."
                    )
            else:
                _embaixo(alvo, bloco)
    return blocos, avisos


def _copia(bloco) -> dict:
    return {
        "tipo": _tipo(getattr(bloco, "tipo", "tabela")),
        "titulo": str(getattr(bloco, "titulo", "") or "").strip(),
        "colunas": [str(c or "").strip() for c in getattr(bloco, "colunas", ())],
        "linhas": [list(l) for l in getattr(bloco, "linhas", ())],
    }


def _tipo(tipo) -> str:
    tipo = normalizar(tipo)
    return tipo if tipo in TIPOS else "tabela"


def _alvo(blocos, bloco, direcao):
    if not blocos:
        return None
    if direcao == "horizontal":
        return blocos[0]
    largura = len(getattr(bloco, "colunas", ()) or (getattr(bloco, "linhas", ()) or [[]])[0])
    for candidato in reversed(blocos):
        if len(candidato["colunas"]) == largura:
            return candidato
    return None


def _embaixo(alvo, bloco) -> None:
    novas = [list(l) for l in getattr(bloco, "linhas", ())]
    colunas = [normalizar(c) for c in getattr(bloco, "colunas", ())]
    if novas and [normalizar(v) for v in novas[0]] == [normalizar(c) for c in alvo["colunas"]]:
        novas = novas[1:]            # o cabeçalho repetido no alto do pedaço
    elif colunas and colunas != [normalizar(c) for c in alvo["colunas"]] and any(colunas):
        # Cabeçalho diferente: o leitor tomou a primeira linha do pedaço por
        # cabeçalho. Ela é dado.
        novas = [list(getattr(bloco, "colunas", ()))] + novas
    # A sobreposição tem uma ou duas linhas, e a da borda pode vir cortada
    # num pedaço e inteira no outro: sai do começo do pedaço seguinte toda
    # linha que já está no fim do anterior, até `LINHAS_NA_EMENDA` + 1.
    fim_do_anterior = {_chave_da_linha(l) for l in alvo["linhas"][-(LINHAS_NA_EMENDA + 1):]}
    corte = 0
    for linha in novas[: LINHAS_NA_EMENDA + 1]:
        if _chave_da_linha(linha) not in fim_do_anterior:
            break
        corte += 1
    alvo["linhas"].extend(novas[corte:])


def _ao_lado(alvo, bloco) -> bool:
    linhas = [list(l) for l in getattr(bloco, "linhas", ())]
    if len(linhas) != len(alvo["linhas"]):
        return False
    existentes = {normalizar(c) for c in alvo["colunas"]}
    novas = [i for i, c in enumerate(getattr(bloco, "colunas", ())) if normalizar(c) not in existentes]
    alvo["colunas"].extend(str(getattr(bloco, "colunas")[i]) for i in novas)
    for destino, origem in zip(alvo["linhas"], linhas):
        destino.extend(origem[i] if i < len(origem) else "" for i in novas)
    return True


def _chave_da_linha(linha) -> tuple:
    return tuple(normalizar(v) for v in linha)


# ------------------------------------------------------------ conferência


def conferir(blocos, pedacos: int = 1, avisos=()) -> Transcricao:
    """Confere e tipa a transcrição. Nada aqui chama modelo."""
    transcricao = Transcricao(avisos=list(avisos), pedacos=pedacos)
    titulos = set()
    for i, bruto in enumerate(blocos, 1):
        bloco = bruto if isinstance(bruto, dict) else _copia(bruto)
        colunas = [c for c in bloco["colunas"]][:MAX_COLUNAS]
        largura = max([len(colunas)] + [len(l) for l in bloco["linhas"]]) if bloco["linhas"] else len(colunas)
        largura = min(largura, MAX_COLUNAS)
        if not largura:
            continue
        colunas = _nomes_das_colunas(colunas, largura)
        tortas, linhas = 0, []
        for linha in bloco["linhas"]:
            valores = ["" if v is None else str(v).strip() for v in linha]
            if len(valores) != largura:
                tortas += 1
                valores = (valores + [""] * largura)[:largura]
            if any(valores):
                linhas.append(valores)
        if not linhas:
            continue
        titulo = _titulo(bloco["titulo"], i, len(blocos), titulos)
        if len(linhas) > MAX_LINHAS_POR_BLOCO:
            transcricao.avisos.append(
                f"`{titulo}` tinha {len(linhas)} linhas; ficaram as {MAX_LINHAS_POR_BLOCO} primeiras."
            )
            linhas = linhas[:MAX_LINHAS_POR_BLOCO]
        if tortas:
            transcricao.avisos.append(
                f"Em `{titulo}`, {tortas} linha(s) vieram com colunas a mais ou a menos e foram alinhadas: confira."
            )

        ilegiveis = [_rotulo_da_linha(l, n) for n, l in enumerate(linhas, 1) if any(_ILEGIVEL.match(v) for v in l)]
        if ilegiveis:
            transcricao.avisos.append(
                f"Em `{titulo}`, {len(ilegiveis)} linha(s) têm célula ilegível no print "
                f"({_lista(ilegiveis)}): ficaram em branco nessas células."
            )
            linhas = [["" if _ILEGIVEL.match(v) else v for v in l] for l in linhas]

        if largura == 1 or bloco["tipo"] == "lista":
            # Lista de códigos repete por engano mais do que de propósito: na
            # emenda dos pedaços ou na leitura (teste real de 2026-10-09, 2
            # repetidos em 227 CRMs). Fica na tabela, e a pessoa fica sabendo.
            contagem = {}
            for linha in linhas:
                contagem[linha[0]] = contagem.get(linha[0], 0) + 1
            repetidos = [v for v, n in contagem.items() if v and n > 1]
            if repetidos:
                transcricao.avisos.append(
                    f"Em `{titulo}`, {len(repetidos)} valor(es) aparecem mais de uma vez ({_lista(repetidos)}): "
                    "confira se o print repete mesmo."
                )

        numericas = [j for j in range(largura) if _coluna_numerica([l[j] for l in linhas])]
        totais = [l for l in linhas if _TOTAL.match(l[0] or "")]
        corpo = [l for l in linhas if not _TOTAL.match(l[0] or "")]
        tipadas = [tuple(_valor(v, j in numericas) for j, v in enumerate(l)) for l in corpo]
        for total in totais:
            transcricao.avisos.append(_conferir_total(titulo, colunas, numericas, tipadas, total))

        transcricao.blocos.append(Bloco(tipo=bloco["tipo"], titulo=titulo, colunas=tuple(colunas), linhas=tuple(tipadas)))
    return transcricao


def _nomes_das_colunas(colunas, largura) -> list:
    nomes, vistos = [], set()
    for j in range(largura):
        nome = (colunas[j] if j < len(colunas) else "") or f"Coluna {j + 1}"
        base, n = nome, 2
        while normalizar(nome) in vistos:
            nome, n = f"{base} ({n})", n + 1
        vistos.add(normalizar(nome))
        nomes.append(nome)
    return nomes


def _titulo(titulo, i, total, usados) -> str:
    # A aba vira `anexo.<aba>` no SQL: nome curto e previsível. Até 31
    # caracteres, o limite do Excel.
    base = "Tabela do print" if total == 1 else f"Print {i}"
    nome = re.sub(r"[\[\]:*?/\\]", " ", titulo or "").strip()[:31] if titulo and total > 1 else base
    nome = nome or base
    while normalizar(nome) in usados:
        nome = f"{base} {len(usados) + 1}"[:31]
    usados.add(normalizar(nome))
    return nome


def _rotulo_da_linha(linha, n) -> str:
    primeiro = next((v for v in linha if v and not _ILEGIVEL.match(v)), "")
    return primeiro[:30] if primeiro else f"linha {n}"


def _lista(itens, n: int = 8) -> str:
    itens = list(itens)
    texto = ", ".join(itens[:n])
    return texto + (f" e mais {len(itens) - n}" if len(itens) > n else "")


# "1.234,56", "R$ 1.234", "12,5%", "-3,2", "(120)", "1.5", "2.461" (milhar).
_NUMERO = re.compile(r"^\(?[-+−]?\s*(?:R\$|US\$|\$)?\s*[-+−]?\d[\d.,\s]*\)?\s*(%|p\.?p\.?|mil|mi)?$", re.I)


def numero_br(texto):
    """O número escrito no print, ou None. Milhar com ponto e decimal com
    vírgula, como o Brasil escreve; "2.461" é dois mil quatrocentos e
    sessenta e um. Percentual fica como está escrito (12,5% → 12.5)."""
    bruto = str(texto or "").strip()
    if not bruto or not _NUMERO.match(bruto):
        return None
    negativo = bruto.startswith("(") and bruto.endswith(")") or "-" in bruto or "−" in bruto
    escala = 1.0
    sufixo = re.search(r"(mil|mi)\s*$", bruto, re.I)
    if sufixo:
        escala = 1_000.0 if sufixo.group(1).lower() == "mil" else 1_000_000.0
    digitos = re.sub(r"[^\d.,]", "", bruto)
    if not re.search(r"\d", digitos):
        return None
    if "," in digitos:
        digitos = digitos.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", digitos):
        digitos = digitos.replace(".", "")
    try:
        valor = float(digitos) * escala
    except ValueError:
        return None
    return -valor if negativo else valor


def _coluna_numerica(valores) -> bool:
    preenchidos = [v for v in valores if v and not _TOTAL.match(v)]
    if not preenchidos:
        return False
    # CRM, CNPJ, EAN e código são texto mesmo sendo só dígitos: o zero à
    # esquerda e o tamanho importam.
    if any(re.fullmatch(r"0\d+", v) or re.fullmatch(r"\d{9,}", v) or re.search(r"[A-Za-z]{2}\s*\d", v) for v in preenchidos):
        return False
    return sum(numero_br(v) is not None for v in preenchidos) >= 0.8 * len(preenchidos)


def _valor(texto, numerico: bool):
    if texto == "":
        return None
    if numerico:
        numero = numero_br(texto)
        if numero is not None:
            return numero
    return texto


def _conferir_total(titulo, colunas, numericas, corpo, total) -> str:
    fecham, nao_fecham = [], []
    for j in numericas:
        escrito = numero_br(total[j])
        if escrito is None:
            continue
        soma = sum(l[j] for l in corpo if isinstance(l[j], float))
        if abs(soma - escrito) <= max(TOLERANCIA_DO_TOTAL * abs(escrito), 0.51):
            fecham.append(colunas[j])
        else:
            nao_fecham.append(f"`{colunas[j]}` (soma {_br(soma)} × total {total[j]})")
    if nao_fecham:
        return (f"Em `{titulo}`, a linha de total não fecha com a soma em {_lista(nao_fecham, 4)}: a leitura "
                "pode ter errado um número, ou o print filtra linhas. A linha de total ficou fora da tabela.")
    if fecham:
        return f"Em `{titulo}`, a linha de total fecha com a soma das linhas ({_lista(fecham, 4)}); ela ficou fora da tabela."
    return f"Em `{titulo}`, a linha de total ficou fora da tabela."


def _br(valor: float) -> str:
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto[:-3] if texto.endswith(",00") else texto


# ------------------------------------------------------------ planilha


def montar_planilha(transcricao: Transcricao) -> bytes:
    """xlsx em memória: uma aba por bloco, números como número. Nada vai
    para disco (ADR-0024)."""
    from openpyxl import Workbook

    if not transcricao.blocos:
        raise AnexoRecusado("Não encontrei uma tabela no print.")
    livro = Workbook()
    livro.remove(livro.active)
    for bloco in transcricao.blocos:
        aba = livro.create_sheet(bloco.titulo)
        aba.append(list(bloco.colunas))
        for linha in bloco.linhas:
            # Texto que começaria fórmula fica texto (mesma regra do preenchimento).
            aba.append([f"'{v}" if isinstance(v, str) and v[:1] in INICIOS_DE_FORMULA else v for v in linha])
    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()
