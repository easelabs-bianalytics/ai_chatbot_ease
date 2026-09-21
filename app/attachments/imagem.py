"""Imagem enviada pelo usuário: validar de verdade e reduzir antes de mandar.

Duas coisas acontecem aqui, e as duas são obrigatórias:

- **Validar pelo conteúdo, não pelo nome.** O `content-type` e a extensão
  vêm do navegador e não valem nada; quem diz se é uma imagem é o decodificador.
- **Reduzir.** O custo da imagem é proporcional à área, não ao tamanho do
  arquivo. Medido contra a API em 2026-09-21: 1920×1080 custa 2.461 tokens
  de entrada, e a mesma imagem em 1024×576 custa 704 — mesma leitura, um
  terço do preço.
"""

import io
from dataclasses import dataclass

from attachments.limites import FORMATOS_DE_IMAGEM, MAX_LADO_DA_IMAGEM, AnexoRecusado

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

        imagem.thumbnail((MAX_LADO_DA_IMAGEM, MAX_LADO_DA_IMAGEM), Image.LANCZOS)
        buffer = io.BytesIO()
        imagem.save(buffer, format="PNG", optimize=True)
        return ImagemPreparada(
            dados=buffer.getvalue(),
            largura=imagem.width,
            altura=imagem.height,
            formato_original=formato,
            reduzida=(imagem.width, imagem.height) != original,
        )
