"""Puxa a Área Médica e o Email MKT para o schema `marketing` (ADR-0032).

    uv run python app/manage.py sincronizar_marketing
    uv run python app/manage.py sincronizar_marketing --fonte area_medica

Em produção roda todo dia de madrugada, como task ECS agendada. Sai com
código 1 se alguma fonte falhou — é o que o ECS registra como falha —, mas
as fontes que deram certo ficam gravadas.
"""

from django.core.management.base import BaseCommand, CommandError

from config.console import usar_utf8_no_console
from marketing.fontes import AreaMedica, EmailMkt
from marketing.sincronizar import FONTES, conectar, sincronizar


class Command(BaseCommand):
    help = "Sincroniza a Área Médica e o Email MKT no schema marketing."

    def add_arguments(self, parser):
        parser.add_argument("--fonte", choices=FONTES, action="append",
                            help="Só esta fonte (pode repetir). Sem ela, as duas.")

    def handle(self, *args, **options):
        usar_utf8_no_console()
        fontes = tuple(options["fonte"] or FONTES)
        area_medica = AreaMedica.do_ambiente() if "area_medica" in fontes else None
        email_mkt = EmailMkt.do_ambiente() if "email_mkt" in fontes else None
        conexao = conectar()
        try:
            resultado = sincronizar(conexao, area_medica, email_mkt, fontes)
        finally:
            conexao.close()
        for fonte, item in resultado.items():
            detalhe = item.get("linhas") if item["status"] == "ok" else item.get("erro")
            self.stdout.write(f"{fonte}: {item['status']} {detalhe}")
        if any(item["status"] != "ok" for item in resultado.values()):
            raise CommandError("alguma fonte do Marketing não sincronizou; veja acima")
