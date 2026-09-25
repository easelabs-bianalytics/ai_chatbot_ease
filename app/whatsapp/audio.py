"""Áudio do WhatsApp: transcrever e decidir se chamou o Jarvis (ADR-0029).

O áudio vira texto e segue o caminho de qualquer pergunta escrita. No
privado, todo áudio de contato liberado é transcrito. No grupo liberado:

- o áudio que RESPONDE (cita) uma mensagem do Jarvis é atendido direto;
- os demais são transcritos só para procurar "Jarvis" — se o nome não
  aparece, a transcrição é descartada na hora, sem registro do conteúdo.

A transcrição é cobrada por minuto de áudio (~US$ 0,003 no
`gpt-4o-mini-transcribe`), não por token: procurar o nome é uma busca no
texto, sem chamada de modelo.
"""

import logging
import os
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Acima disto o áudio não é transcrito: pergunta cabe em um minuto, e o teto
# impede que um áudio longo (reunião, música) vire custo.
MAX_SEGUNDOS = 180
MODELO_PADRAO = "gpt-4o-mini-transcribe"
DOLARES_POR_MINUTO = 0.003

# O vocabulário da casa ajuda o modelo a escrever os nomes como o banco os
# conhece ("sell out", não "celaute"; "PX", não "pé xis").
VOCABULARIO = (
    "Conversa com o Jarvis (J-A-R-V-I-S), o assistente de dados da Ease Labs. "
    "Jarvis, Ease Labs, PX, prescrição, sell out, sell in, market share, MAT, YTD, CDD, painel, "
    "território, representante, GR, brick, Raia Drogasil, Pague Menos, Panvel, Indiana, Aché, "
    "planilha, preencher, Extrato, Canabidiol, Neurologia, Psiquiatria."
)

# O nome e o quanto a grafia da transcrição pode se afastar dele. Em
# 2026-09-25 um áudio "Jarvis, vou te enviar uma planilha" voltou como
# "Javis" — fora da lista fixa de grafias que existia, e no grupo o áudio
# seria descartado. Uma letra de diferença pega javis, jarbis, jervis,
# garvis, jarves, járvis; "jarvisson" (três) continua de fora.
_NOME = "jarvis"
_MAX_DIFERENCA = 1


class TranscricaoFalhou(Exception):
    """O áudio não virou texto: serviço fora, formato estranho, silêncio."""


class Transcritor(ABC):
    @abstractmethod
    def transcrever(self, dados: bytes, mimetype: str) -> str:
        """O texto do áudio. Levanta `TranscricaoFalhou`."""


class TranscritorOpenAI(Transcritor):
    def __init__(self, modelo: str = "", cliente=None):
        self.modelo = modelo or os.environ.get("WHATSAPP_MODELO_TRANSCRICAO", "").strip() or MODELO_PADRAO
        self._cliente = cliente

    @property
    def cliente(self):
        if self._cliente is None:
            from openai import OpenAI

            chave = os.environ.get("AI_PROVIDER_API_KEY", "").strip()
            if not chave:
                raise TranscricaoFalhou("AI_PROVIDER_API_KEY não está definida")
            self._cliente = OpenAI(api_key=chave, timeout=60.0, max_retries=1)
        return self._cliente

    def transcrever(self, dados: bytes, mimetype: str) -> str:
        extensao = "mp3" if "mpeg" in (mimetype or "") else "ogg"
        try:
            resposta = self.cliente.audio.transcriptions.create(
                model=self.modelo,
                file=(f"audio.{extensao}", dados, (mimetype or "audio/ogg").split(";")[0]),
                language="pt",
                prompt=VOCABULARIO,
            )
        except TranscricaoFalhou:
            raise
        except Exception as exc:  # noqa: BLE001 — qualquer falha do serviço vira a mesma mensagem
            raise TranscricaoFalhou(str(exc)[:300]) from exc
        return " ".join(str(getattr(resposta, "text", "") or "").split())


@dataclass
class TranscritorFake(Transcritor):
    """Devolve os textos programados, em ordem. Usado nos testes e quando a
    chave da IA não está configurada."""

    textos: list = field(default_factory=list)
    falhar: bool = False
    recebidos: list = field(default_factory=list)

    def transcrever(self, dados: bytes, mimetype: str) -> str:
        self.recebidos.append((dados, mimetype))
        if self.falhar or not self.textos:
            raise TranscricaoFalhou("fake sem texto programado")
        return self.textos.pop(0)


def transcritor_configurado() -> Transcritor:
    if os.environ.get("AI_PROVIDER_API_KEY", "").strip():
        return TranscritorOpenAI()
    return TranscritorFake()


def _diferenca(a: str, b: str) -> int:
    """Quantas letras separam as duas palavras (distância de edição)."""
    anterior = list(range(len(b) + 1))
    for i, letra_a in enumerate(a, 1):
        atual = [i]
        for j, letra_b in enumerate(b, 1):
            atual.append(min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + (letra_a != letra_b)))
        anterior = atual
    return anterior[-1]


def _parece_jarvis(palavra: str) -> bool:
    if palavra.startswith("ch"):          # "Chárvis": o "ch" é o som do "j"
        palavra = "j" + palavra[2:]
    return abs(len(palavra) - len(_NOME)) <= _MAX_DIFERENCA and _diferenca(palavra, _NOME) <= _MAX_DIFERENCA


def chamou_o_jarvis(texto: str) -> bool:
    """O nome "Jarvis" foi dito no áudio, mesmo com a grafia que a
    transcrição inventou para ele: sem acento, sem caixa e com até uma letra
    de diferença. A transcrição às vezes parte o nome em dois ("jar vis"):
    duas palavras curtas seguidas também contam."""
    sem_acento = unicodedata.normalize("NFD", (texto or "").lower())
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    palavras = re.findall(r"[a-z]+", sem_acento)
    if any(_parece_jarvis(p) for p in palavras):
        return True
    return any(
        len(a) <= 4 and len(b) <= 4 and _parece_jarvis(a + b)
        for a, b in zip(palavras, palavras[1:])
    )


def custo(segundos: int) -> float:
    return round(max(segundos, 1) / 60 * DOLARES_POR_MINUTO, 5)


def transcrever_limpo(transcritor: Transcritor, dados: bytes, mimetype: str) -> str:
    """A transcrição sem espaço sobrando. Áudio mudo ou só ruído volta vazio,
    e vazio é falha: responder a "" seria responder a nada."""
    texto = " ".join((transcritor.transcrever(dados, mimetype) or "").split())
    if not texto:
        raise TranscricaoFalhou("transcrição vazia")
    return texto
