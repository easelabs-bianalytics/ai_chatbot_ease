"""Gera app/knowledge/schema_snapshot.md a partir do banco de negócio.

    uv run python app/manage.py catalog_snapshot

Usa o banco configurado em ANALYTICS_DB_* (ou ANALYTICS_DATABASE_URL), com o
usuário somente leitura. O arquivo gerado entra no hash do catálogo: depois
de regerar, rode os casos sintéticos antes de ir para produção (ADR-0006).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.loader import get_catalog
from catalog.snapshot import DEFAULT_SNAPSHOT_PATH, ler_relacoes, render_snapshot
from config.console import usar_utf8_no_console
from datasource.executors.base import QueryExecutionError
from datasource.executors.factory import get_configured_executor
from datasource.executors.fake import FakeQueryExecutor


def executor_real_ou_erro():
    """Sem banco configurado, a fábrica devolve o executor fake — ótimo para
    rodar a aplicação local, péssimo aqui: o snapshot sairia com dado de
    mentira e a IA passaria a acreditar nele."""
    executor = get_configured_executor()
    if isinstance(executor, FakeQueryExecutor):
        raise CommandError(
            "banco de negócio não configurado: defina ANALYTICS_DB_HOST, "
            "ANALYTICS_DB_PORT, ANALYTICS_DB_NAME, ANALYTICS_DB_USER e "
            "ANALYTICS_DB_PASS (ou ANALYTICS_DATABASE_URL)"
        )
    return executor


class Command(BaseCommand):
    help = "Gera o snapshot do schema real do banco de negócio para a IA."

    def add_arguments(self, parser):
        parser.add_argument(
            "--saida",
            default=str(DEFAULT_SNAPSHOT_PATH),
            help="Arquivo de destino (padrão: app/knowledge/schema_snapshot.md).",
        )

    def handle(self, *args, **options):
        usar_utf8_no_console()
        catalogo = get_catalog()
        executor = executor_real_ou_erro()

        try:
            relacoes = ler_relacoes(executor, catalogo)
        except QueryExecutionError as exc:
            raise CommandError(f"não foi possível ler o schema: {exc}") from exc

        if not relacoes:
            raise CommandError(
                "nenhuma tabela visível para o usuário configurado: confira os "
                "GRANTs (infra/rds/02_criar_usuario_leitura.sql)"
            )

        texto, resumo = render_snapshot(relacoes, catalogo)
        destino = Path(options["saida"])
        destino.write_text(texto + "\n", encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"Snapshot salvo em {destino}"))
        self.stdout.write(
            f"  {resumo['schemas']} schemas · {resumo['relacoes']} tabelas e views · "
            f"{resumo['tabelas_omitidas']} tabela(s) e {resumo['colunas_omitidas']} "
            "coluna(s) omitidas por bloqueio do catálogo"
        )
        self.stdout.write(
            f"  tamanho: {len(texto):,} caracteres (~{len(texto) // 4:,} tokens no prompt)"
        )
