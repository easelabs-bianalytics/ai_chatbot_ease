"""Confere o catálogo: ele é lido por máquina e erra em silêncio.

Um schema esquecido faz a IA receber "não está liberado" para uma pergunta
legítima; uma referência que o próprio validador recusaria faz a IA copiar
algo que nunca vai rodar. Nenhuma das duas coisas aparece num teste de
unidade do orquestrador — aparecem aqui.

    uv run python app/manage.py catalog_check
    uv run python app/manage.py catalog_check --com-banco
"""

from django.core.management.base import BaseCommand, CommandError

from catalog.errors import CatalogError
from catalog.loader import load_catalog
from catalog.management.commands.catalog_snapshot import executor_real_ou_erro
from catalog.snapshot import ler_relacoes
from datasource.executors.base import QueryExecutionError
from datasource.sql_guard import tables_in, validate_sql
from config.console import usar_utf8_no_console


class Command(BaseCommand):
    help = "Valida o catálogo e as consultas de referência (e, com --com-banco, o schema real)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--com-banco",
            action="store_true",
            dest="com_banco",
            help="Confere se as tabelas citadas existem no banco de "
            "ANALYTICS_DATABASE_URL (exige o usuário de leitura, D-01).",
        )

    def handle(self, *args, **options):
        usar_utf8_no_console()

        try:
            catalogo = load_catalog()
        except CatalogError as exc:
            raise CommandError(f"catálogo inválido: {exc}") from exc

        self.stdout.write(self.style.MIGRATE_HEADING("Catálogo"))
        self.stdout.write(f"  schemas            : {', '.join(sorted(catalogo.schemas))}")
        self.stdout.write(f"  tabelas bloqueadas : {', '.join(sorted(catalogo.blocked_tables)) or '—'}")
        for tabela, colunas in sorted(catalogo.blocked_columns.items()):
            self.stdout.write(f"  colunas bloqueadas : {tabela} → {', '.join(sorted(colunas))}")
        self.stdout.write(
            f"  limites            : {catalogo.max_rows} linhas · "
            f"{catalogo.statement_timeout_ms} ms · {catalogo.rows_to_model} linhas para o modelo"
        )
        self.stdout.write(f"  referências        : {len(catalogo.references)}")
        self.stdout.write(f"  hash               : {catalogo.hash}")

        problemas = []

        self.stdout.write(self.style.MIGRATE_HEADING("\nConsultas de referência"))
        tabelas_citadas = set()
        for referencia in catalogo.references:
            resultado = validate_sql(referencia.sql, catalogo)
            tabelas_citadas |= tables_in(referencia.sql)
            if resultado.approved:
                self.stdout.write(f"  {referencia.id} ok  {referencia.title}")
            else:
                problemas.append(f"{referencia.id}: {resultado.reason}")
                self.stdout.write(self.style.ERROR(f"  {referencia.id} RECUSADA — {resultado.reason}"))

        self.stdout.write(self.style.MIGRATE_HEADING("\nTabelas citadas pelas referências"))
        for tabela in sorted(tabelas_citadas):
            self.stdout.write(f"  {tabela}")

        if options["com_banco"]:
            problemas += self._conferir_banco(catalogo, tabelas_citadas)

        if problemas:
            raise CommandError("problemas encontrados:\n- " + "\n- ".join(problemas))

        self.stdout.write(self.style.SUCCESS("\nCatálogo consistente."))

    def _conferir_banco(self, catalogo, tabelas_citadas):
        self.stdout.write(self.style.MIGRATE_HEADING("\nConferência contra o banco"))
        executor = executor_real_ou_erro()
        try:
            # Consulta direta, sem passar pelo validador: o catálogo do
            # sistema é justamente o que ele bloqueia, e aqui a origem é o
            # nosso código, não a IA. Só aparece o que o usuário configurado
            # consegue ler — tabela sem GRANT conta como inexistente, e é
            # isso mesmo que se quer saber.
            existentes = {nome.lower() for nome in ler_relacoes(executor, catalogo)}
        except QueryExecutionError as exc:
            raise CommandError(f"não foi possível conferir o banco: {exc}") from exc

        futuras = catalogo.future_schemas
        problemas = []
        for tabela in sorted(tabelas_citadas):
            if tabela in existentes:
                self.stdout.write(f"  {tabela} ok")
            elif tabela.split(".", 1)[0] in futuras:
                # Previsto e documentado: a IA responde "ainda não disponível".
                self.stdout.write(self.style.WARNING(f"  {tabela} ainda não existe (schema previsto)"))
            else:
                self.stdout.write(self.style.ERROR(f"  {tabela} NÃO EXISTE"))
                problemas.append(f"tabela citada nas referências não existe no banco: {tabela}")
        return problemas
