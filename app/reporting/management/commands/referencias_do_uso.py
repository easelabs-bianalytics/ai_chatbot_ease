"""Mostra as perguntas sem referência que o Jarvis resolveu, como rascunho de referência.

    uv run python app/manage.py referencias_do_uso
    uv run python app/manage.py referencias_do_uso --desde 2026-10-01

Cada uma passou pelo reconhecimento (ADR-0033), foi respondida e não levou 👎.
Revise, dê um id da seção certa e cole em chatbot_bi_referencia_querys.md —
depois rode `run_synthetic_cases --so-gabarito`. Não grava nada.
"""

from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from config.console import usar_utf8_no_console
from reporting import referencias_do_uso


class Command(BaseCommand):
    help = "Rascunhos de consulta de referência a partir dos reconhecimentos que deram certo."

    def add_arguments(self, parser):
        parser.add_argument("--desde", help="Só as respostas a partir desta data, AAAA-MM-DD.")

    def handle(self, *args, **opcoes):
        usar_utf8_no_console()
        desde = None
        if opcoes["desde"]:
            try:
                dia = datetime.strptime(opcoes["desde"], "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError("use --desde AAAA-MM-DD") from exc
            desde = timezone.make_aware(datetime.combine(dia, time.min))

        respostas = referencias_do_uso.pendentes(desde)
        if not respostas:
            self.stdout.write("Nenhuma pergunta sem referência respondida no período.")
            return
        for resposta in respostas:
            self.stdout.write(referencias_do_uso.rascunho(resposta) + "\n")
        self.stdout.write(self.style.SUCCESS(f"{len(respostas)} rascunho(s). Revise antes de colar no documento."))
