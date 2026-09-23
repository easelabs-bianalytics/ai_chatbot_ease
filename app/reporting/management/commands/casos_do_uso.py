"""Transforma os 👎 em rascunhos de caso de validação.

    uv run python app/manage.py casos_do_uso              # acrescenta em casos_do_uso.yaml e marca
    uv run python app/manage.py casos_do_uso --saida -    # só mostra, sem gravar nem marcar
    uv run python app/manage.py casos_do_uso --todas      # inclui os já exportados

Depois, revise os rascunhos e rode `run_synthetic_cases --com-rascunhos`.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from config.console import usar_utf8_no_console
from reporting import casos_do_uso
from reporting.cases import DEFAULT_USO_PATH


class Command(BaseCommand):
    help = "Exporta cada 👎 como rascunho de caso em app/knowledge/casos_do_uso.yaml."

    def add_arguments(self, parser):
        parser.add_argument(
            "--saida",
            default=str(DEFAULT_USO_PATH),
            help="Arquivo onde acrescentar os rascunhos; '-' só mostra, sem marcar nada.",
        )
        parser.add_argument("--todas", action="store_true", help="Inclui os 👎 já exportados.")

    def handle(self, *args, **opcoes):
        usar_utf8_no_console()
        avaliacoes = list(casos_do_uso.pendentes(todas=opcoes["todas"]))
        if not avaliacoes:
            self.stdout.write("Nenhum 👎 novo para exportar.")
            return

        casos = [casos_do_uso.rascunho(a) for a in avaliacoes]
        if opcoes["saida"] == "-":
            self.stdout.write(casos_do_uso.em_yaml(casos))
            return

        novos = casos_do_uso.acrescentar(casos, opcoes["saida"])
        type(avaliacoes[0]).objects.filter(pk__in=[a.pk for a in avaliacoes]).update(
            caso_exportado_em=timezone.now()
        )
        self.stdout.write(self.style.SUCCESS(
            f"{novos} rascunho(s) novo(s) em {opcoes['saida']} "
            f"({len(avaliacoes)} 👎 marcados como exportados)."
        ))
        self.stdout.write("Revise cada um e rode: run_synthetic_cases --com-rascunhos")
