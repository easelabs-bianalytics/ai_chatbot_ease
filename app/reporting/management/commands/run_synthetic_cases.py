"""Roda os casos de validação e gera docs/validation-report.md (Fase 7).

    uv run python app/manage.py run_synthetic_cases --so-gabarito
    uv run python app/manage.py run_synthetic_cases
    uv run python app/manage.py run_synthetic_cases --caso B13-isolado30-go --caso X-vendas-ambiguo
    uv run python app/manage.py run_synthetic_cases --grupo esclarecimento

`--so-gabarito` não chama a IA: roda só as consultas-gabarito no banco, para
provar que cada caso devolve linhas antes de gastar dinheiro com ele.

Precisa do banco de negócio real (túnel aberto, ANALYTICS_DB_*): o banco
sintético não tem as tabelas do documento, e comparar a IA com um executor
fake não prova nada.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ai_orchestrator.provider_factory import get_configured_provider
from ai_orchestrator.providers.fake import FakeAIProvider
from catalog.errors import CatalogError
from catalog.loader import BASE_DIR, get_catalog
from catalog.management.commands.catalog_snapshot import executor_real_ou_erro
from config.console import usar_utf8_no_console
from reporting.cases import load_cases
from reporting.synthetic import (
    APROVADO,
    BLOQUEADOR,
    avaliar_caso,
    conferir_gabarito,
    render_report,
)

RELATORIO = BASE_DIR / "docs" / "validation-report.md"


class Command(BaseCommand):
    help = "Valida a IA com os casos derivados do documento de referência."

    def add_arguments(self, parser):
        parser.add_argument("--caso", action="append", default=[], help="Roda só este caso (repetível).")
        parser.add_argument("--grupo", action="append", default=[], help="Roda só este grupo (repetível).")
        parser.add_argument(
            "--so-gabarito",
            action="store_true",
            dest="so_gabarito",
            help="Não chama a IA: só confere se os gabaritos rodam e devolvem linhas.",
        )
        parser.add_argument(
            "--saida",
            default=str(RELATORIO),
            help="Arquivo do relatório (padrão: docs/validation-report.md).",
        )

    def handle(self, *args, **options):
        usar_utf8_no_console()
        catalogo = get_catalog()
        try:
            suite = load_cases()
        except CatalogError as exc:
            raise CommandError(f"casos inválidos: {exc}") from exc

        casos = [
            c
            for c in suite.casos
            if (not options["caso"] or c.id in options["caso"])
            and (not options["grupo"] or c.grupo in options["grupo"])
        ]
        if not casos:
            raise CommandError("nenhum caso selecionado")

        executor = executor_real_ou_erro()

        if options["so_gabarito"]:
            self._so_gabarito(casos, catalogo, executor)
            return

        provider = get_configured_provider()
        if isinstance(provider, FakeAIProvider):
            raise CommandError(
                "AI_PROVIDER não está configurado: com o provedor fake o relatório "
                "mediria o fake, não a IA (use --so-gabarito para conferir os casos)"
            )

        resultados = []
        for caso in casos:
            resultado = avaliar_caso(caso, suite, catalogo, provider, executor)
            resultados.append(resultado)
            estilo = self.style.SUCCESS if resultado.status == APROVADO else (
                self.style.ERROR if resultado.status == BLOQUEADOR else self.style.WARNING
            )
            self.stdout.write(estilo(f"  {caso.id:32} {resultado.status:10} {'; '.join(resultado.motivos)}"))

        modelo = getattr(provider, "model", "") or type(provider).__name__
        saida = Path(options["saida"])
        saida.write_text(render_report(resultados, catalogo, modelo), encoding="utf-8")
        self.stdout.write(f"\nRelatório: {saida}")

        if any(r.status == BLOQUEADOR for r in resultados):
            raise CommandError("há casos bloqueadores: não vá para produção")

    def _so_gabarito(self, casos, catalogo, executor):
        problemas = []
        for caso in casos:
            if not caso.tem_gabarito:
                continue
            linhas, ms, problema = conferir_gabarito(caso, catalogo, executor)
            if problema:
                problemas.append(f"{caso.id}: {problema}")
                self.stdout.write(self.style.ERROR(f"  {caso.id:32} {problema}"))
            else:
                self.stdout.write(f"  {caso.id:32} {linhas:>4} linhas  {ms:>6} ms")

        if problemas:
            raise CommandError("gabaritos com problema:\n- " + "\n- ".join(problemas))
        self.stdout.write(self.style.SUCCESS("\nTodos os gabaritos rodam e devolvem linhas."))
