"""Conversa com a Evolution API, que conecta o número do Jarvis ao WhatsApp.

Interface abstrata com duas implementações (ADR-0005): a real fala HTTP com
a Evolution, que em produção é um service próprio no ECS
(`evolution.cockpit-prod-jarvis.local:8080`, ADR-0028); a fake guarda o que teria sido enviado e é a dos testes — nenhum
teste abre conexão.

Formatos confirmados na referência (Evolution v2.3.7):

- envio de texto: `POST /message/sendText/{instancia}`
  `{"number", "text", "quoted"?}` → `{"key": {"id"}}`;
- envio de arquivo: `POST /message/sendMedia/{instancia}`
  `{"number", "mediatype": image|document, "mimetype", "media": base64,
  "fileName", "caption"}`;
- "digitando": `POST /chat/sendPresence/{instancia}` `{"number", "presence", "delay"}`;
- arquivo recebido: `POST /chat/getBase64FromMediaMessage/{instancia}`
  `{"message": {"key": {...}}}` → `{"base64": "..."}`.
"""

import base64
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import quote
from uuid import uuid4

import requests

logger = logging.getLogger(__name__)

TIMEOUT = 15
# Imagem e planilha sobem em base64 no corpo e demoram mais que texto.
TIMEOUT_DE_ARQUIVO = 60
# (conexão, leitura): o "digitando" não espera a resposta, ver `digitando`.
TIMEOUT_DO_DIGITANDO = (3, 0.5)


class WhatsAppIndisponivel(Exception):
    """A Evolution não respondeu, ou respondeu erro. Quem chama registra e
    segue: a resposta fica gravada no banco (e visível no chat web)."""


class InstanciaInexistente(WhatsAppIndisponivel):
    """A Evolution respondeu, mas a instância ainda não foi criada (404).
    Em 2026-09-24, na primeira abertura da página de conexão em produção,
    isso aparecia como "A Evolution não respondeu"."""


@dataclass(frozen=True)
class Citacao:
    """A mensagem que a resposta cita — num grupo, a pergunta de quem chamou."""

    id: str
    jid: str
    texto: str = ""
    participante: str = ""


class ClienteWhatsApp(ABC):
    @abstractmethod
    def enviar_texto(self, jid: str, texto: str, citar: Citacao | None = None) -> str:
        """Manda o texto e devolve o id da mensagem no WhatsApp."""

    @abstractmethod
    def enviar_arquivo(self, jid: str, dados: bytes, nome: str, mimetype: str,
                       tipo: str = "document", legenda: str = "") -> str:
        """Manda imagem (`tipo="image"`) ou documento e devolve o id."""

    @abstractmethod
    def digitando(self, jid: str) -> None:
        """Mostra "digitando…". Cosmético: nunca levanta."""

    @abstractmethod
    def baixar_midia(self, mensagem: dict) -> bytes:
        """Os bytes de um arquivo recebido (`data` do evento)."""

    def estado(self) -> dict:
        return {"estado": "desconhecido"}

    def conectar(self) -> dict:
        """QR de pareamento: `{"qr": "data:image/png;base64,..."}`."""
        return {}

    def configurar(self, url_do_webhook: str) -> None:
        """Cria a instância, se preciso, e aponta o webhook."""

    def grupos(self) -> list:
        """Grupos de que o número participa: [{"jid", "nome"}]."""
        return []

    def participantes(self, grupo_jid: str) -> list:
        """Membros do grupo: [{"id", "numero"}]. `id` pode ser o @lid, e
        `numero` são os dígitos do número por trás dele."""
        return []


class EvolutionCliente(ClienteWhatsApp):
    def __init__(self, base_url=None, api_key=None, instancia=None, sessao=None):
        self._base = (base_url or os.environ.get("EVOLUTION_API_BASE_URL", "http://127.0.0.1:8080")).rstrip("/")
        self._chave = api_key or os.environ.get("EVOLUTION_API_KEY", "")
        self._instancia = instancia or os.environ.get("EVOLUTION_INSTANCE_NAME", "jarvis")
        self._http = sessao or requests.Session()

    def _post(self, caminho, corpo, timeout=TIMEOUT) -> dict:
        try:
            resposta = self._http.post(
                f"{self._base}{caminho}",
                headers={"apikey": self._chave, "Content-Type": "application/json"},
                json=corpo, timeout=timeout,
            )
            resposta.raise_for_status()
            return resposta.json() if resposta.content else {}
        except (requests.RequestException, ValueError) as exc:
            raise WhatsAppIndisponivel(f"{caminho}: {exc}") from exc

    def _get(self, caminho) -> dict:
        try:
            resposta = self._http.get(f"{self._base}{caminho}", headers={"apikey": self._chave}, timeout=TIMEOUT)
            if resposta.status_code == 404 and caminho.startswith("/instance/"):
                raise InstanciaInexistente(f"{caminho}: a instância {self._instancia} não existe")
            resposta.raise_for_status()
            return resposta.json() if resposta.content else {}
        except (requests.RequestException, ValueError) as exc:
            raise WhatsAppIndisponivel(f"{caminho}: {exc}") from exc

    @staticmethod
    def _id(corpo) -> str:
        return (corpo.get("key") or {}).get("id") or corpo.get("id") or f"sem-id-{uuid4()}"

    def enviar_texto(self, jid, texto, citar=None) -> str:
        corpo = {"number": jid, "text": texto}
        if citar is not None:
            chave = {"id": citar.id, "remoteJid": citar.jid, "fromMe": False}
            if citar.participante:
                chave["participant"] = citar.participante
            corpo["quoted"] = {"key": chave, "message": {"conversation": citar.texto or ""}}
        return self._id(self._post(f"/message/sendText/{self._instancia}", corpo))

    def enviar_arquivo(self, jid, dados, nome, mimetype, tipo="document", legenda="") -> str:
        corpo = {
            "number": jid, "mediatype": tipo, "mimetype": mimetype,
            "media": base64.b64encode(dados).decode("ascii"), "fileName": nome, "caption": legenda,
        }
        return self._id(self._post(f"/message/sendMedia/{self._instancia}", corpo, timeout=TIMEOUT_DE_ARQUIVO))

    def digitando(self, jid) -> None:
        """A Evolution só responde ao sendPresence DEPOIS do `delay` (20 s),
        mas o "digitando…" já aparece quando ela recebe o pedido. Esperar a
        resposta prendia o atendimento 15 s por etapa, até o timeout, e
        enchia o log de traceback (produção, 2026-09-24). Então: manda e não
        espera — o timeout de leitura curto é o caminho normal."""
        try:
            self._http.post(
                f"{self._base}/chat/sendPresence/{self._instancia}",
                headers={"apikey": self._chave, "Content-Type": "application/json"},
                json={"number": jid, "presence": "composing", "delay": 20000},
                timeout=TIMEOUT_DO_DIGITANDO,
            )
        except requests.ReadTimeout:
            pass
        except requests.RequestException as exc:
            logger.info("Não consegui mostrar \"digitando\": %s", exc)

    def baixar_midia(self, mensagem) -> bytes:
        corpo = self._post(
            f"/chat/getBase64FromMediaMessage/{self._instancia}",
            {"message": {"key": mensagem.get("key") or {}, "message": mensagem.get("message") or {}},
             "convertToMp4": False},
            timeout=TIMEOUT_DE_ARQUIVO,
        )
        try:
            return base64.b64decode(corpo.get("base64") or "")
        except ValueError as exc:
            raise WhatsAppIndisponivel(f"arquivo em base64 inválido: {exc}") from exc

    def estado(self) -> dict:
        try:
            corpo = self._get(f"/instance/connectionState/{self._instancia}")
        except InstanciaInexistente:
            return {"estado": "sem_instancia"}
        estado = {"estado": (corpo.get("instance") or {}).get("state") or corpo.get("state") or "desconhecido"}
        try:
            instancias = self._get(f"/instance/fetchInstances?instanceName={self._instancia}")
        except WhatsAppIndisponivel:
            return estado
        primeira = (instancias[0] if isinstance(instancias, list) and instancias else instancias) or {}
        # O número pareado, para preencher WHATSAPP_NUMERO_JARVIS sem erro.
        estado["conectado_como"] = str(primeira.get("ownerJid") or "")
        estado["nome_do_perfil"] = str(primeira.get("profileName") or "")
        return estado

    def conectar(self) -> dict:
        corpo = self._get(f"/instance/connect/{self._instancia}")
        return {"qr": corpo.get("base64") or "", "codigo": corpo.get("pairingCode") or ""}

    def grupos(self) -> list:
        corpo = self._get(f"/group/fetchAllGroups/{self._instancia}?getParticipants=false")
        itens = corpo if isinstance(corpo, list) else []
        return sorted(
            ({"jid": str(g.get("id") or ""), "nome": str(g.get("subject") or "")} for g in itens if g.get("id")),
            key=lambda g: g["nome"].lower(),
        )

    def participantes(self, grupo_jid: str) -> list:
        corpo = self._get(f"/group/participants/{self._instancia}?groupJid={quote(grupo_jid)}")
        itens = corpo.get("participants") if isinstance(corpo, dict) else corpo
        return [
            {"id": str(p.get("id") or ""), "numero": re.sub(r"\D", "", str(p.get("phoneNumber") or "").split("@")[0])}
            for p in itens or () if isinstance(p, dict)
        ]

    def configurar(self, url_do_webhook: str) -> None:
        """Instância com grupos LIGADOS (a trava é o nosso cadastro, ADR-0028),
        chamada recusada, nada marcado como lido e o webhook só com mensagens."""
        try:
            existentes = self._get(f"/instance/fetchInstances?instanceName={self._instancia}")
        except WhatsAppIndisponivel:
            # A Evolution responde 404 para instância que não existe. Se o
            # problema for outro, a criação logo abaixo falha e diz.
            existentes = []
        if not existentes:
            self._post("/instance/create", {
                "instanceName": self._instancia, "integration": "WHATSAPP-BAILEYS", "qrcode": True,
            })
        self._post(f"/settings/set/{self._instancia}", {
            "rejectCall": True, "msgCall": "O Jarvis só responde por mensagem.",
            "groupsIgnore": False, "alwaysOnline": False, "readMessages": False,
            "readStatus": False, "syncFullHistory": False,
        })
        self._post(f"/webhook/set/{self._instancia}", {"webhook": {
            "enabled": True, "url": url_do_webhook, "byEvents": False, "base64": False,
            "events": ["MESSAGES_UPSERT"],
        }})


@dataclass
class ClienteFake(ClienteWhatsApp):
    """Guarda o que teria saído. Usado nos testes e quando a Evolution não
    está configurada (desenvolvimento local)."""

    enviados: list = field(default_factory=list)
    midias: dict = field(default_factory=dict)
    membros: dict = field(default_factory=dict)
    falhar: bool = False

    def participantes(self, grupo_jid) -> list:
        return list(self.membros.get(grupo_jid, []))

    def _registrar(self, **envio) -> str:
        if self.falhar:
            raise WhatsAppIndisponivel("fake configurado para falhar")
        envio["id"] = f"fake-{uuid4().hex[:16]}"
        self.enviados.append(envio)
        return envio["id"]

    def enviar_texto(self, jid, texto, citar=None) -> str:
        return self._registrar(tipo="texto", jid=jid, texto=texto, citar=citar.id if citar else "")

    def enviar_arquivo(self, jid, dados, nome, mimetype, tipo="document", legenda="") -> str:
        return self._registrar(tipo=tipo, jid=jid, nome=nome, mimetype=mimetype, legenda=legenda, dados=dados)

    def digitando(self, jid) -> None:
        pass

    def baixar_midia(self, mensagem) -> bytes:
        chave = (mensagem.get("key") or {}).get("id", "")
        if chave not in self.midias:
            raise WhatsAppIndisponivel("mídia não programada no fake")
        return self.midias[chave]


def cliente_configurado() -> ClienteWhatsApp:
    """O cliente real quando a Evolution está configurada; senão, o fake."""
    if os.environ.get("EVOLUTION_API_KEY", "").strip():
        return EvolutionCliente()
    return ClienteFake()
