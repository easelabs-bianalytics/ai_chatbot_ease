"""Configuração do canal WhatsApp, lida do ambiente (ADR-0028).

- `WHATSAPP_NUMERO_JARVIS`: o número do Jarvis, só dígitos (5511...). É o que
  reconhece a menção "@5511..." num grupo. Enquanto o chip não existe, fica
  vazio e só "@jarvis" escrito à mão chama.
- `WHATSAPP_LID_JARVIS`: o identificador escondido do Jarvis (`...@lid`), que
  o WhatsApp usa na menção em parte dos grupos. Aparece na página de conexão
  do Admin depois de parear.
- `WHATSAPP_WEBHOOK_TOKEN`: o segredo no caminho do webhook. Vazio = webhook
  recusando tudo.
- `EVOLUTION_API_BASE_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE_NAME`: a
  Evolution; sem chave, o cliente é o fake (nada sai).
"""

import os

from whatsapp.models import so_digitos


def numero_do_jarvis() -> str:
    return so_digitos(os.environ.get("WHATSAPP_NUMERO_JARVIS", ""))


def lid_do_jarvis() -> str:
    return os.environ.get("WHATSAPP_LID_JARVIS", "").strip()


def token_do_webhook() -> str:
    return os.environ.get("WHATSAPP_WEBHOOK_TOKEN", "").strip()


def webhook_so_local() -> bool:
    """Recusar webhook que passou por proxy. Só serve quando a Evolution
    chama o Jarvis direto, sem ALB; em produção fica desligado (0), porque o
    webhook volta pelo ALB."""
    return os.environ.get("WHATSAPP_WEBHOOK_SO_LOCAL", "1").strip() not in ("0", "false", "")


def url_interna_do_webhook() -> str:
    """Para onde a Evolution manda os eventos. Em produção é o domínio do
    Jarvis, pelo ALB (WHATSAPP_WEBHOOK_BASE_URL); o segredo no caminho é a
    trava."""
    base = os.environ.get("WHATSAPP_WEBHOOK_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/api/whatsapp/webhook/{token_do_webhook()}/"
