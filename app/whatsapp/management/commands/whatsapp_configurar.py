"""Cria a instância da Evolution e aponta o webhook (ADR-0028).

    uv run python app/manage.py whatsapp_configurar          # configura e mostra o estado
    uv run python app/manage.py whatsapp_configurar --qr     # e grava o QR em whatsapp_qr.png

É o mesmo botão "Configurar a instância" da página de conexão do Admin, para
quem estiver num shell (ECS Exec) em vez do navegador.
"""

import base64
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from config.console import usar_utf8_no_console
from whatsapp import config
from whatsapp.cliente import EvolutionCliente, WhatsAppIndisponivel, cliente_configurado


class Command(BaseCommand):
    help = "Configura a instância da Evolution (grupos, chamadas, webhook) e mostra o estado."

    def add_arguments(self, parser):
        parser.add_argument("--qr", action="store_true", help="Grava o QR de pareamento em whatsapp_qr.png.")

    def handle(self, *args, **opcoes):
        usar_utf8_no_console()
        cliente = cliente_configurado()
        if not isinstance(cliente, EvolutionCliente):
            raise CommandError("EVOLUTION_API_KEY não está configurada neste ambiente.")
        if not config.token_do_webhook():
            raise CommandError("WHATSAPP_WEBHOOK_TOKEN vazio: o webhook recusaria todos os eventos.")
        try:
            cliente.configurar(config.url_interna_do_webhook())
            estado = cliente.estado()["estado"]
            self.stdout.write(self.style.SUCCESS(f"Instância configurada. Estado: {estado}"))
            if opcoes["qr"] and estado != "open":
                qr = cliente.conectar().get("qr", "")
                if not qr:
                    raise CommandError("A Evolution não devolveu QR.")
                Path("whatsapp_qr.png").write_bytes(base64.b64decode(qr.split(",", 1)[-1]))
                self.stdout.write("QR gravado em whatsapp_qr.png (vale por alguns segundos).")
        except WhatsAppIndisponivel as exc:
            raise CommandError(f"A Evolution não respondeu: {exc}") from exc
