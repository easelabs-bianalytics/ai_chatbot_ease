"""Conversa com a IA pelo terminal, com o pipeline de verdade (Fase 5).

    uv run python app/manage.py chat_local
    uv run python app/manage.py chat_local --fake-ai        # sem gastar
    uv run python app/manage.py chat_local --fake-db        # sem tocar o RDS

Mostra, a cada resposta, o que a interface web vai mostrar depois: a
consulta executada, a referência usada, o tempo, as linhas e o custo. É o
jeito mais barato de olhar no olho da IA antes de rodar a suíte inteira.

Comandos: /nova (outra conversa), /sql (consulta da última resposta),
/status (gasto do mês e catálogo), /sair.
"""

import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from ai_orchestrator import budget
from ai_orchestrator.models import AIReply
from ai_orchestrator.orchestrator import handle_message
from ai_orchestrator.provider_factory import get_configured_provider
from ai_orchestrator.providers.fake import FakeAIProvider
from catalog.loader import get_catalog
from config.console import usar_utf8_no_console
from conversations.models import Conversation
from datasource.executors.factory import get_configured_executor
from datasource.executors.fake import FakeQueryExecutor
from datasource.models import QueryRun
from messaging.channels.base import InboundMessage
from messaging.channels.fake import FakeChannel
from messaging.services import ingest_inbound_message

USUARIO = "chat_local"


class Command(BaseCommand):
    help = "Conversa com a IA pelo terminal, usando o pipeline completo."

    def add_arguments(self, parser):
        parser.add_argument("--fake-ai", action="store_true", dest="fake_ai",
                            help="Usa o provedor fake: não chama a OpenAI nem gasta.")
        parser.add_argument("--fake-db", action="store_true", dest="fake_db",
                            help="Usa o executor fake: não consulta o banco de negócio.")
        parser.add_argument("--pergunta", action="append", default=[],
                            help="Faz a pergunta, mostra a resposta e sai (repetível).")

    def handle(self, *args, **options):
        usar_utf8_no_console()
        catalogo = get_catalog()
        provider = FakeAIProvider(catalogo) if options["fake_ai"] else get_configured_provider()
        executor = FakeQueryExecutor() if options["fake_db"] else get_configured_executor()
        usuario, _ = get_user_model().objects.get_or_create(username=USUARIO)
        conversa = Conversation.objects.create(user=usuario, title="[chat_local]")

        self.stdout.write(self.style.MIGRATE_HEADING("Chat local"))
        self.stdout.write(f"  IA      : {getattr(provider, 'model', '') or type(provider).__name__}")
        self.stdout.write(f"  redação : {getattr(provider, 'answer_model', '') or '—'}")
        self.stdout.write(f"  banco   : {type(executor).__name__}")
        self.stdout.write(f"  catálogo: {catalogo.hash[:12]} · {len(catalogo.references)} referências")
        self.stdout.write("  comandos: /nova  /sql  /status  /sair\n")

        ultima = None
        for pergunta in options["pergunta"]:
            ultima = self._responder(conversa, pergunta, provider, executor, catalogo)

        if options["pergunta"]:
            return

        while True:
            try:
                texto = input("\nvocê > ").strip()
            except (EOFError, KeyboardInterrupt):
                self.stdout.write("\nAté logo.")
                return

            if not texto:
                continue
            if texto == "/sair":
                self.stdout.write("Até logo.")
                return
            if texto == "/nova":
                conversa = Conversation.objects.create(user=usuario, title="[chat_local]")
                self.stdout.write(self.style.SUCCESS("Conversa nova (o histórico anterior sai do contexto)."))
                continue
            if texto == "/status":
                self._status(catalogo)
                continue
            if texto == "/sql":
                self._sql(ultima)
                continue

            ultima = self._responder(conversa, texto, provider, executor, catalogo)

    def _responder(self, conversa, pergunta, provider, executor, catalogo):
        mensagem, _ = ingest_inbound_message(
            conversa,
            InboundMessage(
                conversation_id=conversa.pk, client_message_id=str(uuid.uuid4()), text=pergunta
            ),
        )
        reply = handle_message(
            mensagem, channel=FakeChannel(), provider=provider, executor=executor, catalog=catalogo
        )

        self.stdout.write("\n" + self.style.SUCCESS("IA > ") + (reply.reply_text or "(sem texto)"))
        self._rodape(reply)
        return reply

    def _rodape(self, reply: AIReply):
        consultas = list(QueryRun.objects.filter(ai_reply=reply).order_by("attempt"))
        executada = next((q for q in reversed(consultas) if q.status == QueryRun.Status.SUCCESS), None)

        partes = [f"decisão={reply.decision}"]
        if reply.rule:
            partes.append(f"regra={reply.rule}")
        if executada is not None:
            partes.append(f"referência={executada.reference_query_id or '—'}")
            partes.append(f"linhas={executada.row_count}")
            partes.append(f"banco={executada.duration_ms} ms")
        elif consultas:
            partes.append(f"consulta recusada: {consultas[-1].guard_reason or consultas[-1].error}")

        chamadas = list(reply.calls.all())
        secoes = next(
            (c.request.get("secoes") for c in chamadas if c.request.get("secoes")), None
        )
        if secoes:
            partes.append(f"seções={'+'.join(secoes)}")
        cache = sum(int(c.response.get("tokens_em_cache") or 0) for c in chamadas)
        partes.append(f"tokens={reply.tokens_input}+{reply.tokens_output} (cache {cache})")
        partes.append(f"custo=US$ {float(reply.cost_estimate or 0):.4f}")
        partes.append(f"tempo={reply.latency_ms} ms")
        self.stdout.write(self.style.HTTP_INFO("      " + " · ".join(partes)))

    def _sql(self, reply):
        if reply is None:
            self.stdout.write("Nenhuma pergunta ainda.")
            return
        for consulta in QueryRun.objects.filter(ai_reply=reply).order_by("attempt"):
            cabecalho = f"-- tentativa {consulta.attempt} · {consulta.guard_result} · {consulta.status}"
            self.stdout.write(self.style.MIGRATE_HEADING(cabecalho))
            if consulta.guard_reason:
                self.stdout.write(self.style.WARNING(f"-- {consulta.guard_reason}"))
            self.stdout.write(consulta.sql)

    def _status(self, catalogo):
        situacao = budget.situacao()
        teto = situacao["teto"]
        self.stdout.write(f"  gasto do mês : US$ {float(situacao['gasto']):.4f}")
        self.stdout.write(
            f"  teto         : {'US$ ' + f'{float(teto):.2f}' if teto else 'sem limite configurado'}"
        )
        if situacao["perto_do_limite"]:
            self.stdout.write(self.style.WARNING("  atenção: acima de 80% do teto do mês"))
        if situacao["excedido"]:
            self.stdout.write(self.style.ERROR("  teto atingido: as perguntas não vão mais ao modelo"))
        self.stdout.write(f"  catálogo     : {catalogo.hash[:12]}")
        self.stdout.write(f"  referências  : {len(catalogo.references)}")
