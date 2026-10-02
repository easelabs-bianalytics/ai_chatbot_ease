"""Carrega a planilha da Base 660 em `marketing.medicos_660` (ADR-0032).

    uv run python app/manage.py carregar_medicos_660 "Médicos 660 - Informações MKT.xlsx"

Não é agendado: a Base 660 é um retrato fixo. Rodar de novo, com uma planilha
nova, substitui tudo numa transação. A carga entra em
`marketing.sincronizacoes` como a fonte `medicos_660`, que é de onde o Jarvis
diz de quando é o dado.
"""

from django.core.management.base import BaseCommand

from config.console import usar_utf8_no_console
from marketing.base_660 import FONTE, gravar_base_660, ler_planilha
from marketing.sincronizar import _registrar_fim, _registrar_inicio, conectar, preparar


class Command(BaseCommand):
    help = "Carrega a planilha da Base 660 no schema marketing."

    def add_arguments(self, parser):
        parser.add_argument("planilha", help="Caminho do .xlsx da Base 660")

    def handle(self, *args, **options):
        usar_utf8_no_console()
        linhas = ler_planilha(options["planilha"])
        conexao = conectar()
        try:
            preparar(conexao)
            identificador = _registrar_inicio(conexao, FONTE)
            resumo = gravar_base_660(conexao, linhas)
            conexao.commit()
            _registrar_fim(conexao, identificador, "ok", resumo)
        finally:
            conexao.close()
        self.stdout.write(f"{FONTE}: ok {resumo}")
