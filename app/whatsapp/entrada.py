"""O evento da Evolution, lido para o que o Jarvis precisa saber (ADR-0028).

Evento `messages.upsert` (Evolution v2):

    {"event": "messages.upsert", "instance": "jarvis",
     "data": {"key": {"remoteJid": "5511...@s.whatsapp.net" | "1203...@g.us",
                      "fromMe": false, "id": "3EB0...",
                      "participant": "5511...@s.whatsapp.net"},   # em grupo
              "pushName": "Paulo",
              "message": {"conversation": "..."} | {"extendedTextMessage": {...}}
                         | {"imageMessage": {...}} | {"documentMessage": {...}}
                         | {"audioMessage": {...}} | {"reactionMessage": {...}},
              "contextInfo": {...}}}

**Número de quem escreveu.** O WhatsApp passou a esconder o número atrás de
um identificador próprio (`...@lid`) em parte das mensagens. A Evolution
manda o número de verdade num campo à parte (`senderPn`, `remoteJidAlt`,
`participantAlt`), e é ele que casa com o cadastro. Sem nenhum número, a
mensagem de um contato individual não tem como ser liberada, e cai no log.
"""

import re
from dataclasses import dataclass, field

TEXTO, IMAGEM, DOCUMENTO, AUDIO, REACAO = "texto", "imagem", "documento", "audio", "reacao"

# Acima disto não é pergunta: é texto colado por engano (o mesmo limite do chat web).
MAX_CARACTERES = 2000


@dataclass(frozen=True)
class Recebida:
    id: str
    jid: str                      # o chat: pessoa (@s.whatsapp.net / @lid) ou grupo (@g.us)
    grupo: bool
    numero: str                   # quem escreveu, só dígitos ("" se o WhatsApp escondeu)
    nome: str
    tipo: str
    texto: str = ""
    mencionados: tuple = ()       # jids marcados com @ na mensagem
    citada_id: str = ""           # a mensagem que esta responde (citação)
    citada_participante: str = ""
    reacao: str = ""              # o emoji, em REACAO ("" = reação removida)
    reacao_alvo: str = ""         # id da mensagem que recebeu a reação
    arquivo_nome: str = ""
    arquivo_mimetype: str = ""
    bruto: dict = field(default_factory=dict, repr=False)


def formas_do_numero(numero: str) -> set:
    """O mesmo celular brasileiro com e sem o nono dígito.

    O WhatsApp identifica muitos celulares do Brasil SEM o 9 da frente: em
    2026-09-24 o próprio número do Jarvis veio como 553190054127, e não
    5531990054127. Quem cadastra um contato digita o número como conhece,
    com o 9; comparar só a forma exata ignoraria a pessoa em silêncio."""
    numero = re.sub(r"\D", "", str(numero or ""))
    formas = {numero} if numero else set()
    if numero.startswith("55") and len(numero) == 13 and numero[4] == "9":
        formas.add(numero[:4] + numero[5:])
    elif numero.startswith("55") and len(numero) == 12 and numero[4] in "6789":
        formas.add(numero[:4] + "9" + numero[4:])
    return formas



def _digitos(jid: str) -> str:
    if not jid or jid.endswith("@lid") or jid.endswith("@g.us"):
        return ""
    return re.sub(r"\D", "", jid.split("@")[0].split(":")[0])


def _contexto(data: dict, corpo: dict) -> dict:
    """contextInfo mora no tipo da mensagem ou, na Evolution v2, no topo."""
    for chave in ("extendedTextMessage", "imageMessage", "documentMessage", "audioMessage"):
        contexto = (corpo.get(chave) or {}).get("contextInfo")
        if contexto:
            return contexto
    documento = (corpo.get("documentWithCaptionMessage") or {}).get("message") or {}
    contexto = (documento.get("documentMessage") or {}).get("contextInfo")
    return contexto or data.get("contextInfo") or {}


def ler(payload: dict) -> Recebida | None:
    """None para o que não é mensagem (outros eventos, formato estranho)."""
    if not isinstance(payload, dict) or payload.get("event") not in ("messages.upsert", "MESSAGES_UPSERT"):
        return None
    data = payload.get("data") or {}
    if isinstance(data, list):          # alguns envios chegam em lote de um
        data = data[0] if data else {}
    chave = data.get("key") or {}
    jid = str(chave.get("remoteJid") or "")
    ident = str(chave.get("id") or "")
    if not jid or not ident or chave.get("fromMe") or jid == "status@broadcast":
        # fromMe: eco do que o próprio Jarvis mandou. Status não é conversa.
        return None

    grupo = jid.endswith("@g.us")
    autor = str(chave.get("participant") or "") if grupo else jid
    numero = next(
        (d for d in (
            _digitos(str(chave.get("senderPn") or data.get("senderPn") or "")),
            _digitos(str(chave.get("participantAlt") or "")) if grupo else _digitos(str(chave.get("remoteJidAlt") or "")),
            _digitos(autor),
        ) if d),
        "",
    )

    corpo = data.get("message") or {}
    contexto = _contexto(data, corpo)
    comum = dict(
        id=ident, jid=jid, grupo=grupo, numero=numero, nome=str(data.get("pushName") or "")[:120],
        mencionados=tuple(str(m) for m in contexto.get("mentionedJid") or ()),
        citada_id=str(contexto.get("stanzaId") or ""),
        citada_participante=str(contexto.get("participant") or ""),
        bruto=data,
    )

    if "reactionMessage" in corpo:
        reacao = corpo["reactionMessage"] or {}
        return Recebida(tipo=REACAO, reacao=str(reacao.get("text") or ""),
                        reacao_alvo=str((reacao.get("key") or {}).get("id") or ""), **comum)

    documento = corpo.get("documentMessage") or (
        ((corpo.get("documentWithCaptionMessage") or {}).get("message") or {}).get("documentMessage")
    )
    if documento:
        return Recebida(tipo=DOCUMENTO, texto=_limpo(documento.get("caption")),
                        arquivo_nome=str(documento.get("fileName") or documento.get("title") or "arquivo")[:255],
                        arquivo_mimetype=str(documento.get("mimetype") or ""), **comum)
    if corpo.get("imageMessage"):
        imagem = corpo["imageMessage"]
        return Recebida(tipo=IMAGEM, texto=_limpo(imagem.get("caption")), arquivo_nome="imagem.jpg",
                        arquivo_mimetype=str(imagem.get("mimetype") or "image/jpeg"), **comum)
    if "audioMessage" in corpo or "pttMessage" in corpo:
        return Recebida(tipo=AUDIO, **comum)

    texto = corpo.get("conversation") or (corpo.get("extendedTextMessage") or {}).get("text")
    if not texto:
        return None                     # figurinha, contato, localização: fora do escopo
    return Recebida(tipo=TEXTO, texto=_limpo(texto), **comum)


def _limpo(texto) -> str:
    return str(texto or "").strip()[:MAX_CARACTERES]


def sem_mencao(texto: str, numero_do_jarvis: str, lid_do_jarvis: str = "") -> str:
    """Tira o "@5511..." (o WhatsApp põe o número, ou o @lid, no texto ao
    marcar) e o "@jarvis" digitado. Sobra a pergunta."""
    padroes = [r"@jarvis\b"]
    for marca in (numero_do_jarvis, lid_do_jarvis.split("@")[0]):
        if marca:
            padroes.append(rf"@\+?{re.escape(marca)}\b")
    limpo = re.sub("|".join(padroes), " ", texto or "", flags=re.I)
    return " ".join(limpo.split()).strip(" ,:;-")


def marcou_o_jarvis(recebida: Recebida, numero_do_jarvis: str, lid_do_jarvis: str = "") -> bool:
    """O Jarvis foi marcado: pelo número, pelo identificador escondido (@lid)
    ou pelo "@jarvis" escrito à mão."""
    for jid in recebida.mencionados:
        if numero_do_jarvis and _digitos(jid) in formas_do_numero(numero_do_jarvis):
            return True
        if lid_do_jarvis and jid.split("@")[0] == lid_do_jarvis.split("@")[0]:
            return True
    return bool(re.search(r"@jarvis\b", recebida.texto or "", re.I))
