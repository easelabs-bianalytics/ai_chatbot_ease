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
    "Jarvis, Ease Labs, PX, prescrição, sell out, sell in, market share, MAT, YTD, CDD, painel, "
    "território, representante, GR, brick, Raia Drogasil, Pague Menos, Panvel, Indiana, Aché, "
    "planilha, preencher, Extrato, Canabidiol, Neurologia, Psiquiatria."
)

# "Jarvis" e as grafias que a transcrição costuma produzir para ele.
_JARVIS = re.compile(r"\b(?:jarvis|jarves|jarviz|djarvis|jarvi)\b")


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


def chamou_o_jarvis(texto: str) -> bool:
    """O nome "Jarvis" foi dito no áudio (sem acento e sem caixa)."""
    sem_acento = unicodedata.normalize("NFD", (texto or "").lower())
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return bool(_JARVIS.search(sem_acento))


def custo(segundos: int) -> float:
    return round(max(segundos, 1) / 60 * DOLARES_POR_MINUTO, 5)


def transcrever_limpo(transcritor: Transcritor, dados: bytes, mimetype: str) -> str:
    """A transcrição sem espaço sobrando. Áudio mudo ou só ruído volta vazio,
    e vazio é falha: responder a "" seria responder a nada."""
    texto = " ".join((transcritor.transcrever(dados, mimetype) or "").split())
    if not texto:
        raise TranscricaoFalhou("transcrição vazia")
    return texto
