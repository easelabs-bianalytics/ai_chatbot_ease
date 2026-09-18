"""Relatório de uso do Jarvis no terminal, ou em CSV (Fase 8, FR-16).

    uv run python app/manage.py bi_report
    uv run python app/manage.py bi_report --dias 7
    uv run python app/manage.py bi_report --desde 2026-09-01 --ate 2026-10-01
    uv run python app/manage.py bi_report --csv uso-setembro.csv

Lê só a auditoria do banco da aplicação: não chama a IA, não toca no banco de
negócio e pode rodar a qualquer hora sem custo.
"""

import csv
from datetime import datetime, time
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ai_orchestrator.models import AIReply
from config.console import usar_utf8_no_console
from reporting.services import DECISOES, montar_relatorio

LARGURA = 68


class Command(BaseCommand):
    help = "Uso, taxa de resposta, lacunas, correções, falhas, latência e custo."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=30, help="Janela em dias (padrão: 30).")
        parser.add_argument("--desde", help="Início, AAAA-MM-DD (vence --dias).")
        parser.add_argument("--ate", help="Fim exclusivo, AAAA-MM-DD.")
        parser.add_argument("--csv", dest="csv", help="Grava a série diária neste arquivo.")

    def handle(self, *args, **opcoes):
        usar_utf8_no_console()
        inicio, fim = self._periodo(opcoes)
        r = montar_relatorio(inicio=inicio, fim=fim, dias=opcoes["dias"])

        if not r.perguntas:
            self.stdout.write(self.style.WARNING(
                f"Nenhuma pergunta entre {self._dia(r.inicio)} e {self._dia(r.fim)}."
            ))
            return

        self._titulo(f"Jarvis · uso de {self._dia(r.inicio)} a {self._dia(r.fim)}")
        self._linha("Perguntas", r.perguntas)
        self._linha("Pessoas", r.pessoas)
        self._linha("Conversas", r.conversas)
        self._linha("Planilhas baixadas", r.planilhas)

        self._titulo("Como as perguntas terminaram")
        for decisao, rotulo in DECISOES.items():
            n = r.decisoes.get(decisao, 0)
            if n:
                self._linha(rotulo, f"{n:>5}   {n / r.perguntas:>5.0%}")
        self._linha("Saiu com número", f"{r.taxa_com_dado:.0%}")

        self._titulo("Consultas ao banco")
        self._linha("Executadas", r.consultas)
        self._linha("Corrigidas na 2ª tentativa", r.consultas_corrigidas)
        self._linha("Erro do banco", r.consultas_com_erro)
        self._linha("Tempo estourado", r.consultas_estouradas)
        self._linha("Respostas reescritas por ancoragem", r.reescritas)

        self._titulo("Tempo até a resposta (com consulta)")
        self._linha("Mediana", f"{r.percentil(0.5) / 1000:.1f} s")
        self._linha("p95", f"{r.percentil(0.95) / 1000:.1f} s", alerta=r.percentil(0.95) > 20000)
        self._linha("Mais demorada", f"{r.percentil(1.0) / 1000:.1f} s")

        self._titulo("Custo")
        self._linha("Total no período", f"US$ {r.custo:.4f}")
        self._linha("Por pergunta", f"US$ {r.custo_por_pergunta}")
        self._linha("Projeção para 30 dias", f"US$ {r.custo_projetado_mes}")
        self._linha("Tokens", f"{r.tokens_entrada:,} entrada · {r.tokens_saida:,} saída".replace(",", "."))

        if r.regras:
            self._titulo("Respostas decididas por regra, sem IA")
            for regra, n in r.regras.items():
                self._linha(regra, n)

        self._titulo(f"Lacunas do catálogo em aberto ({r.lacunas_abertas})")
        if r.lacunas:
            for lacuna in r.lacunas:
                self.stdout.write(f"  {lacuna.data}  {lacuna.pergunta}")
                if lacuna.motivo:
                    self.stdout.write(self.style.WARNING(f"          {lacuna.motivo}"))
        else:
            self.stdout.write("  Nenhuma. Tudo que perguntaram, a base respondeu.")

        if opcoes["csv"]:
            self._gravar_csv(opcoes["csv"], r)

    # ---- período ---------------------------------------------------------
    def _periodo(self, opcoes):
        def ler(texto, rotulo):
            if not texto:
                return None
            try:
                dia = datetime.strptime(texto, "%Y-%m-%d").date()
            except ValueError as erro:
                raise CommandError(f"{rotulo} precisa estar em AAAA-MM-DD: {texto}") from erro
            return timezone.make_aware(datetime.combine(dia, time.min))

        inicio, fim = ler(opcoes["desde"], "--desde"), ler(opcoes["ate"], "--ate")
        if inicio and fim and fim <= inicio:
            raise CommandError("--ate precisa ser depois de --desde")
        return inicio, fim

    # ---- saída -----------------------------------------------------------
    def _dia(self, quando):
        return timezone.localtime(quando).strftime("%d/%m/%Y")

    def _titulo(self, texto):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(texto))
        self.stdout.write("-" * LARGURA)

    def _linha(self, rotulo, valor, alerta=False):
        texto = f"  {rotulo:<38} {valor:>26}"
        self.stdout.write(self.style.WARNING(texto) if alerta else texto)

    def _gravar_csv(self, caminho, r):
        """Uma linha por dia: é o formato que abre numa planilha e vira
        gráfico sem ninguém precisar reformatar nada."""
        with open(caminho, "w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";")
            escritor.writerow(["dia", "perguntas", "com_numero", "custo_usd"])
            for dia in r.por_dia:
                escritor.writerow([dia.data, dia.perguntas, dia.com_dado, f"{dia.custo:.6f}"])
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Série diária gravada em {caminho}"))
