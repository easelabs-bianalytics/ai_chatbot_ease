"""Imagem enviada pelo usuário: validar de verdade e reduzir antes de mandar.

Duas coisas acontecem aqui, e as duas são obrigatórias:

- **Validar pelo conteúdo, não pelo nome.** O `content-type` e a extensão
  vêm do navegador e não valem nada; quem diz se é uma imagem é o decodificador.
- **Reduzir pela área, sem apagar o texto.** O custo da imagem é a área, não
  o tamanho do arquivo (1920×1080 mediu 2.461 tokens; 1024×576, 704). Mas
  reduzir todo print a 1.280 px no lado maior apagava a lista alta e a
  faixa larga (conversas 44 e 75): o print longo agora é lido em pedaços,
  cada um do tamanho que o modelo lê sem reduzir (ADR-0035).
"""

import io
import math
from dataclasses import dataclass

from attachments.limites import (
    FORMATOS_DE_IMAGEM,
    MAX_LADO_POR_LEITURA,
    MAX_PEDACOS_DO_PRINT,
    MAX_PIXELS_POR_LEITURA,
    RAZAO_DE_PRINT_LONGO,
    SOBREPOSICAO_DOS_PEDACOS,
    AnexoRecusado,
)

# Tokens por mil pixels, ajustado sobre as duas medições reais de
# 2026-09-21 (704 tokens em 589 mil pixels, 2.461 em 2,07 milhões). Serve
# para estimar custo antes de chamar, não para cobrar.
TOKENS_POR_MIL_PIXELS = 1.19


@dataclass(frozen=True)
class ImagemPreparada:
    dados: bytes
    largura: int
    altura: int
    formato_original: str
    reduzida: bool
    pedacos: int = 1

    @property
    def tokens_estimados(self) -> int:
        return round(self.largura * self.altura / 1000 * TOKENS_POR_MIL_PIXELS)


# Miniatura que fica na conversa (a prévia do print, como nas outras IAs).
# 480 px e JPEG 72: legível como lembrança do que foi enviado, e pequena o
# bastante para morar no banco — medida no print real de 2026-09-21. O
# original, reduzido para o modelo, continua sendo descartado.
LADO_DA_MINIATURA = 480
QUALIDADE_DA_MINIATURA = 72


def miniatura(dados: bytes) -> bytes:
    """JPEG pequeno a partir da imagem já preparada (PNG)."""
    from PIL import Image

    with Image.open(io.BytesIO(dados)) as imagem:
        imagem = imagem.convert("RGB")
        imagem.thumbnail((LADO_DA_MINIATURA, LADO_DA_MINIATURA), Image.LANCZOS)
        buffer = io.BytesIO()
        imagem.save(buffer, format="JPEG", quality=QUALIDADE_DA_MINIATURA, optimize=True)
        return buffer.getvalue()


def preparar(dados: bytes) -> ImagemPreparada:
    """Decodifica, recusa o que não for imagem, reduz e devolve PNG.

    PNG de propósito na saída: o custo depende das dimensões, não dos bytes,
    e JPEG borraria justamente o texto pequeno de um print — que é o que a
    pessoa quer que seja lido.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(dados)) as sonda:
            formato = (sonda.format or "").upper()
            sonda.verify()
    except UnidentifiedImageError as exc:
        raise AnexoRecusado("Esse arquivo não é uma imagem que eu consiga abrir.") from exc
    except Exception as exc:
        raise AnexoRecusado("Não consegui ler essa imagem.") from exc

    if formato not in FORMATOS_DE_IMAGEM:
        aceitos = ", ".join(sorted(FORMATOS_DE_IMAGEM))
        raise AnexoRecusado(f"Formato de imagem não aceito. Use {aceitos}.")

    # `verify` consome o arquivo: para trabalhar na imagem é preciso abrir de novo.
    with Image.open(io.BytesIO(dados)) as imagem:
        original = (imagem.width, imagem.height)
        if imagem.mode in ("RGBA", "LA", "P"):
            # Fundo branco no lugar da transparência: print com fundo
            # transparente viraria texto preto em fundo preto.
            fundo = Image.new("RGB", imagem.size, (255, 255, 255))
            convertida = imagem.convert("RGBA")
            fundo.paste(convertida, mask=convertida.split()[-1])
            imagem = fundo
        elif imagem.mode != "RGB":
            imagem = imagem.convert("RGB")

        escala = _escala(imagem.width, imagem.height)
        if escala < 1:
            imagem = imagem.resize(
                (max(1, int(imagem.width * escala)), max(1, int(imagem.height * escala))), Image.LANCZOS
            )
        buffer = io.BytesIO()
        imagem.save(buffer, format="PNG", optimize=True)
        return ImagemPreparada(
            dados=buffer.getvalue(),
            largura=imagem.width,
            altura=imagem.height,
            formato_original=formato,
            reduzida=(imagem.width, imagem.height) != original,
            pedacos=_quantos_pedacos(imagem.width, imagem.height),
        )


def _longo(largura: int, altura: int) -> bool:
    return max(largura, altura) / max(1, min(largura, altura)) > RAZAO_DE_PRINT_LONGO


def _comprimento_do_pedaco(curto: int) -> int:
    return max(1, min(MAX_LADO_POR_LEITURA, MAX_PIXELS_POR_LEITURA // max(1, curto)))


def _quantos_pedacos(largura: int, altura: int) -> int:
    longo, curto = max(largura, altura), min(largura, altura)
    if not _longo(largura, altura):
        return 1
    comprimento = _comprimento_do_pedaco(curto)
    if longo <= comprimento:
        return 1
    passo = max(1, comprimento - SOBREPOSICAO_DOS_PEDACOS)
    return 1 + math.ceil((longo - comprimento) / passo)


def _escala(largura: int, altura: int) -> float:
    """Quanto reduzir. Print comum: cabe numa leitura (área e lado). Print
    longo: o lado curto cabe numa leitura e o longo vira pedaços — reduzido
    só o bastante para caber em `MAX_PEDACOS_DO_PRINT`."""
    if not _longo(largura, altura):
        return min(1.0, math.sqrt(MAX_PIXELS_POR_LEITURA / (largura * altura)),
                   MAX_LADO_POR_LEITURA / max(largura, altura))
    escala = min(1.0, MAX_LADO_POR_LEITURA / min(largura, altura))
    while _quantos_pedacos(int(largura * escala), int(altura * escala)) > MAX_PEDACOS_DO_PRINT:
        escala *= 0.9
    return escala


def pedacos(dados: bytes) -> tuple:
    """`(pedaços em PNG, direção)`. Um pedaço só para o print comum.

    A direção diz ao leitor como os pedaços se juntam: "vertical" (de cima
    para baixo, as linhas continuam) ou "horizontal" (da esquerda para a
    direita, as colunas continuam)."""
    from PIL import Image

    try:
        imagem = Image.open(io.BytesIO(dados))
    except Exception:  # noqa: BLE001 — já foi validada na subida; na dúvida, vai inteira
        return [dados], ""
    with imagem:
        largura, altura = imagem.size
        total = _quantos_pedacos(largura, altura)
        if total <= 1:
            return [dados], ""
        vertical = altura >= largura
        longo, curto = (altura, largura) if vertical else (largura, altura)
        comprimento = _comprimento_do_pedaco(curto)
        passo = max(1, comprimento - SOBREPOSICAO_DOS_PEDACOS)
        saida = []
        for i in range(total):
            # O último pedaço fica mais curto, e não recuado até caber inteiro:
            # recuado, ele repetia ~65 linhas do anterior (lista de 224 CRMs
            # transcrita com 290, teste real de 2026-10-09). A sobreposição é
            # sempre a mesma, e a emenda tira as linhas repetidas dela.
            inicio = i * passo
            fim = min(inicio + comprimento, longo)
            caixa = (0, inicio, largura, fim) if vertical else (inicio, 0, fim, altura)
            buffer = io.BytesIO()
            imagem.crop(caixa).save(buffer, format="PNG", optimize=True)
            saida.append(buffer.getvalue())
        return saida, "vertical" if vertical else "horizontal"
