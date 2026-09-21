"""API do chat (ADR-0007). Tudo exige login (ADR-0011)."""

from pathlib import Path

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_orchestrator import progresso
from ai_orchestrator.tasks import process_message
from conversations.models import Conversation, Project
from catalog.loader import get_catalog
from datasource.executors.base import QueryExecutionError
from datasource.executors.factory import get_configured_executor
from datasource.export import montar_planilha
from datasource.models import DataExport, QueryRun
from datasource.sql_guard import validate_sql
from messaging.channels.web import WebChannel
from messaging.models import Message
from messaging.services import ingest_inbound_message
from attachments import deposito
from attachments.imagem import preparar as preparar_imagem
from attachments.limites import EXTENSOES_DE_PLANILHA, MAX_BYTES, AnexoRecusado
from attachments.planilha import ler_estrutura

_channel = WebChannel()


def _conversation_json(conversation):
    return {
        "id": conversation.pk,
        "title": conversation.title,
        "status": conversation.status,
        "project": conversation.project_id,
        "position": conversation.position,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def _project_json(project):
    return {"id": project.pk, "name": project.name, "created_at": project.created_at.isoformat()}


def _nome_de_projeto(bruto):
    nome = " ".join(str(bruto or "").split())[:80]
    if not nome:
        raise ValueError("dê um nome ao projeto")
    return nome


def _fonte(resposta, mostrar_custo: bool):
    """De onde saiu a resposta: a consulta que rodou, a referência em que se
    baseou, quando e com quantas linhas (FR da Fase 6).

    É o que permite ao usuário confiar no número sem confiar na IA — e ao
    time de BI conferir uma resposta estranha sem abrir o Admin."""
    pergunta = resposta.in_reply_to
    reply = getattr(pergunta, "ai_reply", None) if pergunta is not None else None
    if reply is None:
        return None

    consultas = sorted(reply.query_runs.all(), key=lambda q: q.attempt)
    executada = next(
        (q for q in reversed(consultas) if q.status == QueryRun.Status.SUCCESS), None
    )
    fonte = {
        "decisao": reply.decision,
        "regra": reply.rule,
        "respondida_em": reply.created_at.isoformat(),
        "tentativas": len(consultas),
        "consulta": None,
    }
    if executada is not None:
        fonte["consulta"] = {
            "sql": executada.sql,
            "referencia": executada.reference_query_id,
            "linhas": executada.row_count,
            "cortada": executada.truncated,
            "duracao_ms": executada.duration_ms,
        }
        pedido = bool((reply.raw_response or {}).get("excel"))
        # Uma linha só é um número, e ele já está no texto da resposta: um
        # botão de planilha ali só promete algo que não acrescenta nada.
        # Com duas ou mais, a planilha é o jeito de levar o resultado inteiro,
        # mesmo quando a resposta é só texto. Pedido explícito sempre vence.
        fonte["excel"] = pedido or (executada.row_count or 0) > 1
        fonte["excel_pedido"] = pedido
        grafico = (reply.raw_response or {}).get("grafico")
        amostra = executada.result_sample or {}
        if grafico and amostra.get("rows"):
            # O gráfico é desenhado no navegador com os números da consulta.
            fonte["grafico"] = grafico
            fonte["dados"] = {"columns": amostra.get("columns", []), "rows": amostra["rows"]}
    origem = (reply.raw_response or {}).get("grafico_de")
    if origem and not fonte.get("grafico"):
        # Ajuste de gráfico (regra `ajuste_de_grafico`): a resposta não rodou
        # consulta nenhuma; os números vêm da que desenhou o gráfico original.
        anterior = Message.objects.filter(pk=origem).select_related("in_reply_to__ai_reply").first()
        anterior_reply = getattr(getattr(anterior, "in_reply_to", None), "ai_reply", None)
        consulta = (
            anterior_reply.query_runs.filter(status=QueryRun.Status.SUCCESS).order_by("-attempt").first()
            if anterior_reply
            else None
        )
        amostra = (consulta.result_sample or {}) if consulta else {}
        if amostra.get("rows"):
            fonte["grafico"] = (reply.raw_response or {}).get("grafico")
            fonte["dados"] = {"columns": amostra.get("columns", []), "rows": amostra["rows"]}

    sugestoes = (reply.raw_response or {}).get("sugestoes")
    if sugestoes:
        fonte["sugestoes"] = sugestoes

    raw = reply.raw_response or {}
    if raw.get("blocos"):
        # Resposta em blocos (ADR-0025): a tela desenha na ordem, com os
        # dados de cada consulta citada. O gráfico solto dá lugar aos blocos.
        fonte["blocos"] = raw["blocos"]
        fonte["dados_blocos"] = raw.get("dados_blocos") or {}
        fonte.pop("grafico", None)
        fonte.pop("dados", None)
    if raw.get("investigacao"):
        # Uma investigação roda várias consultas: o painel de fonte mostra
        # todas, cada uma com a hipótese que testou. A planilha de download
        # sairia de uma só delas, escolhida ao acaso — melhor não oferecer.
        fonte["investigacao"] = raw["investigacao"]
        fonte["excel"] = False
    if mostrar_custo:
        fonte["custo_usd"] = float(reply.cost_estimate or 0)
        fonte["tokens"] = (reply.tokens_input or 0) + (reply.tokens_output or 0)
        fonte["tempo_ms"] = reply.latency_ms
    return fonte


def _message_json(message, mostrar_custo: bool = False):
    dados = {
        "id": message.pk,
        "direction": message.direction,
        "text": message.content,
        "status": message.status,
        "created_at": message.created_at.isoformat(),
    }
    if message.anexo_tipo:
        # O que a conversa guarda do anexo: tipo e nome. O arquivo em si não
        # existe mais (ADR-0024); `planilha_pronta` diz se a preenchida ainda
        # está no prazo de download.
        dados["anexo"] = {
            "tipo": message.anexo_tipo,
            "nome": message.anexo_nome,
            "planilha_pronta": bool(message.anexo_resposta_token),
        }
        if message.anexo_miniatura:
            dados["anexo"]["miniatura"] = (
                f"/api/conversations/{message.conversation_id}/messages/{message.pk}/miniatura/"
            )
    if message.direction == message.Direction.INBOUND and message.status in (
        message.Status.RECEIVED, message.Status.PROCESSING,
    ):
        # O que o Jarvis está fazendo agora ("Testando: a queda foi
        # concentrada?"), para a tela não ficar em "Pensando…" por minutos.
        andamento = progresso.ler(message.pk)
        if andamento:
            dados["progresso"] = andamento
    if message.direction == message.Direction.OUTBOUND:
        dados["in_reply_to"] = message.in_reply_to_id
        dados["fonte"] = _fonte(message, mostrar_custo)
        pergunta = message.in_reply_to
        if pergunta is not None and pergunta.anexo_resposta_token:
            # A planilha preenchida mora na pergunta, que é quem trouxe o
            # arquivo; o botão de baixar fica na resposta, onde a pessoa lê.
            dados["planilha_preenchida"] = {
                "pergunta": pergunta.pk,
                "nome": pergunta.anexo_resposta_nome,
            }
    return dados


class ConversationListCreateView(APIView):
    def get(self, request):
        """Lista as conversas do usuário, ou só as que casam com `q`.

        A busca olha o título e o texto das mensagens: quem procura "ruptura"
        quase nunca lembra do título, lembra do que perguntou. O filtro é do
        próprio usuário — conversa de outro nunca entra no resultado."""
        conversations = Conversation.objects.visiveis().filter(user=request.user)
        busca = str(request.query_params.get("q") or "").strip()[:100]
        if busca:
            conversations = conversations.filter(
                Q(title__icontains=busca) | Q(messages__content__icontains=busca)
            ).distinct()
        return Response({
            "conversations": [_conversation_json(c) for c in conversations],
            "busca": busca,
        })

    def post(self, request):
        title = str(request.data.get("title") or "").strip()[:200]
        conversation = Conversation.objects.create(user=request.user, title=title)
        return Response(_conversation_json(conversation), status=status.HTTP_201_CREATED)


class ConversationOrderView(APIView):
    """Grava a ordem que o usuário montou arrastando a lista.

    Recebe os ids na ordem em que ficaram na tela e escreve 1, 2, 3… em
    `position`. Ids de outra pessoa são ignorados em silêncio — o filtro por
    usuário resolve isso antes de escrever qualquer coisa, e responder
    "não existe" confirmaria que existe.
    """

    def patch(self, request):
        ids = request.data.get("ids")
        if not isinstance(ids, list):
            return Response(
                {"error": "envie a lista de ids em `ids`"}, status=status.HTTP_400_BAD_REQUEST
            )

        posicao = {}
        for i, bruto in enumerate(ids[:500], start=1):
            try:
                posicao[int(bruto)] = i
            except (TypeError, ValueError):
                return Response({"error": "id inválido"}, status=status.HTTP_400_BAD_REQUEST)

        conversas = list(
            Conversation.objects.visiveis().filter(user=request.user, pk__in=posicao)
        )
        for conversa in conversas:
            conversa.position = posicao[conversa.pk]
        # Só `position`: arrastar é organizar, não conversar. Se `updated_at`
        # fosse junto, reordenar a lista faria toda conversa mexida parecer
        # de agora e embaralharia o próprio critério de "recentes".
        Conversation.objects.bulk_update(conversas, ["position"])
        return Response({"ordenadas": len(conversas)})


class ConversationDetailView(APIView):
    """Renomear, arquivar, mover para um projeto e excluir (ADR-0018).

    Excluir é lógico: a conversa some da tela, mas a auditoria (pergunta,
    consulta executada, custo) continua — apagar de verdade é assunto da
    política de retenção (O-08), não de um clique."""

    def _conversation(self, request, conversation_id):
        return get_object_or_404(
            Conversation.objects.visiveis(), pk=conversation_id, user=request.user
        )

    def patch(self, request, conversation_id):
        conversation = self._conversation(request, conversation_id)
        campos = []

        if "title" in request.data:
            titulo = " ".join(str(request.data.get("title") or "").split())[:200]
            if not titulo:
                return Response(
                    {"error": "o título não pode ficar vazio"}, status=status.HTTP_400_BAD_REQUEST
                )
            conversation.title = titulo
            campos.append("title")

        if "status" in request.data:
            novo_status = request.data.get("status")
            if novo_status not in Conversation.Status.values:
                return Response({"error": "situação inválida"}, status=status.HTTP_400_BAD_REQUEST)
            conversation.status = novo_status
            campos.append("status")

        if "project" in request.data:
            projeto_id = request.data.get("project")
            if projeto_id in (None, ""):
                conversation.project = None
            else:
                # Projeto de outra pessoa responde como inexistente, igual à
                # conversa: não confirma que ele existe.
                conversation.project = get_object_or_404(
                    Project, pk=projeto_id, user=request.user
                )
            campos.append("project")

        if campos:
            # Sem `updated_at`: organizar não é conversar. A lista é ordenada
            # pela última atividade, e mover para uma pasta não pode fazer a
            # conversa parecer de hoje.
            conversation.save(update_fields=campos)
            conversation.refresh_from_db(fields=["updated_at"])
        return Response(_conversation_json(conversation))

    def delete(self, request, conversation_id):
        conversation = self._conversation(request, conversation_id)
        conversation.deleted_at = timezone.now()
        conversation.save(update_fields=["deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectListCreateView(APIView):
    def get(self, request):
        projetos = Project.objects.filter(user=request.user)
        return Response({"projects": [_project_json(p) for p in projetos]})

    def post(self, request):
        try:
            nome = _nome_de_projeto(request.data.get("name"))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        projeto = Project.objects.create(user=request.user, name=nome)
        return Response(_project_json(projeto), status=status.HTTP_201_CREATED)


class ProjectDetailView(APIView):
    def _projeto(self, request, project_id):
        return get_object_or_404(Project, pk=project_id, user=request.user)

    def patch(self, request, project_id):
        projeto = self._projeto(request, project_id)
        try:
            projeto.name = _nome_de_projeto(request.data.get("name"))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        projeto.save(update_fields=["name", "updated_at"])
        return Response(_project_json(projeto))

    def delete(self, request, project_id):
        # As conversas voltam para a lista geral (SET_NULL); nada é apagado.
        self._projeto(request, project_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MessageListCreateView(APIView):
    """Mensagens de uma conversa.

    A conversa é sempre buscada com `user=request.user`: pedir a de outra
    pessoa devolve 404, e não 403, para não confirmar que ela existe.
    """

    def _conversation(self, request, conversation_id):
        return get_object_or_404(
            Conversation.objects.visiveis(), pk=conversation_id, user=request.user
        )

    def get(self, request, conversation_id):
        conversation = self._conversation(request, conversation_id)
        # A fonte de cada resposta vem da auditoria da pergunta; sem o
        # prefetch seriam três consultas por mensagem a cada polling.
        messages = conversation.messages.select_related(
            "in_reply_to__ai_reply"
        ).prefetch_related("in_reply_to__ai_reply__query_runs")

        # O navegador busca só o que chegou depois do que ele já tem.
        after = request.query_params.get("after")
        if after:
            try:
                messages = messages.filter(id__gt=int(after))
            except ValueError:
                return Response(
                    {"error": "parâmetro after inválido"}, status=status.HTTP_400_BAD_REQUEST
                )

        mostrar_custo = bool(request.user.is_staff)
        return Response({"messages": [_message_json(m, mostrar_custo) for m in messages]})

    def post(self, request, conversation_id):
        conversation = self._conversation(request, conversation_id)
        payload = {**request.data, "conversation_id": conversation.pk}

        try:
            inbound = _channel.parse_inbound(payload)
        except KeyError as exc:
            return Response(
                {"error": f"campo obrigatório ausente: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        message, created = ingest_inbound_message(conversation, inbound)

        # Perguntar numa conversa arquivada é voltar ao assunto: ela sai do
        # arquivo, senão a resposta chegaria num lugar escondido da lista.
        if created and conversation.status == Conversation.Status.ARCHIVED:
            conversation.status = Conversation.Status.OPEN
            conversation.save(update_fields=["status", "updated_at"])

        if not created:
            return Response(
                {
                    "message_id": message.pk,
                    "conversation_id": conversation.pk,
                    "created": False,
                },
                status=status.HTTP_200_OK,
            )

        # A resposta é montada fora da requisição (ADR-0003) e aparece no
        # polling quando ficar pronta.
        process_message.delay(message.pk, _channel.name)

        return Response(
            {
                "message_id": message.pk,
                "conversation_id": conversation.pk,
                "created": True,
                "status": "queued",
            },
            status=status.HTTP_202_ACCEPTED,
        )


# Limite da planilha: bem acima das 500 linhas da conversa, porque o arquivo
# não passa pela IA (não custa token), mas finito, para uma lista gigante
# não pesar no banco de negócio. O tempo máximo da consulta continua valendo.
EXPORT_MAX_ROWS = 50_000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MessageExcelView(APIView):
    """Planilha Excel com o resultado da resposta (ADR-0020).

    Roda de novo a consulta que a resposta usou — aprovada pelo validador de
    novo, com o limite da planilha — e devolve o `.xlsx`. Não passa pela IA.
    Cada download fica registrado em `DataExport`."""

    def get(self, request, conversation_id, message_id):
        conversation = get_object_or_404(
            Conversation.objects.visiveis(), pk=conversation_id, user=request.user
        )
        resposta = get_object_or_404(
            Message.objects.select_related("in_reply_to__ai_reply"),
            pk=message_id,
            conversation=conversation,
            direction=Message.Direction.OUTBOUND,
        )
        pergunta = resposta.in_reply_to
        reply = getattr(pergunta, "ai_reply", None) if pergunta is not None else None
        consulta = (
            reply.query_runs.filter(status=QueryRun.Status.SUCCESS).order_by("-attempt").first()
            if reply is not None
            else None
        )
        if consulta is None:
            return Response(
                {"error": "esta resposta não tem dados para exportar"},
                status=status.HTTP_404_NOT_FOUND,
            )

        registro = DataExport(user=request.user, message=resposta, sql=consulta.sql)
        catalogo = get_catalog()
        guard = validate_sql(consulta.sql, catalogo, max_rows=EXPORT_MAX_ROWS)
        if not guard.approved:
            registro.status, registro.error = DataExport.Status.ERROR, guard.reason
            registro.save()
            return Response({"error": "a consulta não passou no validador"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            resultado = get_configured_executor().run(guard.sql, max_rows=EXPORT_MAX_ROWS)
        except QueryExecutionError as exc:
            registro.status, registro.error = DataExport.Status.ERROR, str(exc)
            registro.save()
            return Response(
                {"error": "não consegui gerar a planilha agora; tente de novo em instantes"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        agora = timezone.localtime()
        observacao = (
            f"Lista cortada em {EXPORT_MAX_ROWS:,} linhas; refine o filtro para ter o restante.".replace(",", ".")
            if resultado.truncated
            else "Lista completa."
        )
        conteudo = montar_planilha(
            resultado.columns,
            resultado.rows,
            {
                "pergunta": pergunta.content,
                "gerada_em": agora.strftime("%d/%m/%Y %H:%M"),
                "linhas": resultado.row_count,
                "observacao": observacao,
                "referencia": consulta.reference_query_id,
                "sql": consulta.sql,
            },
        )

        registro.status = DataExport.Status.OK
        registro.row_count = resultado.row_count
        registro.truncated = resultado.truncated
        registro.duration_ms = resultado.duration_ms
        registro.save()

        nome = slugify(conversation.title or pergunta.content)[:50] or "consulta"
        http = HttpResponse(conteudo, content_type=XLSX)
        http["Content-Disposition"] = f'attachment; filename="jarvis_{nome}_{agora:%Y%m%d-%H%M}.xlsx"'
        return http


# ---------------------------------------------------------------- anexos

CSV_CONTENT_TYPE = "text/csv; charset=utf-8"


class AnexoView(APIView):
    """Recebe o anexo, valida, resume e devolve uma etiqueta (ADR-0024).

    O arquivo **não é salvo**: os bytes vão para o depósito com prazo
    (`attachments/deposito.py`) e o que volta ao navegador é só o token e o
    resumo. A validação acontece aqui, e não no worker, para a pessoa saber
    na hora que o arquivo é grande demais — e para arquivo recusado nunca
    chegar a custar uma chamada de modelo.

    Não é por conversa de propósito: anexar é o primeiro gesto de uma
    pergunta nova, e exigir conversa criaria uma vazia na lateral a cada
    anexo desistido. O token é aleatório e só vira pergunta pelo POST de
    mensagens, que já confere de quem é a conversa.
    """

    def post(self, request):
        arquivo = request.FILES.get("arquivo")
        if arquivo is None:
            return Response({"error": "nenhum arquivo enviado"}, status=status.HTTP_400_BAD_REQUEST)

        if arquivo.size > MAX_BYTES:
            limite = MAX_BYTES // (1024 * 1024)
            return Response(
                {"error": f"O arquivo tem mais de {limite} MB. Envie um recorte menor."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        nome = (arquivo.name or "arquivo")[:255]
        dados = arquivo.read()

        try:
            if Path(nome).suffix.lower() in EXTENSOES_DE_PLANILHA:
                estrutura = ler_estrutura(nome, dados)
                resumo = estrutura.resumo
                tipo = Message.Anexo.PLANILHA
                detalhe = {"linhas": estrutura.linhas, "colunas": [c.nome for c in estrutura.colunas]}
            else:
                preparada = preparar_imagem(dados)
                # Guarda a imagem REDUZIDA, não a original: é ela que vai ao
                # modelo, e o original não serve para mais nada.
                dados = preparada.dados
                resumo = (
                    f"Imagem {preparada.formato_original} de {preparada.largura}×{preparada.altura}"
                    + (" (reduzida)" if preparada.reduzida else "")
                )
                tipo = Message.Anexo.IMAGEM
                detalhe = {
                    "largura": preparada.largura,
                    "altura": preparada.altura,
                    "tokens_estimados": preparada.tokens_estimados,
                }
        except AnexoRecusado as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        token = deposito.guardar(dados)
        return Response(
            {"token": token, "tipo": tipo, "nome": nome, "resumo": resumo, "detalhe": detalhe},
            status=status.HTTP_201_CREATED,
        )


class MessagePlanilhaView(APIView):
    """Baixa a planilha que o Jarvis preencheu (ADR-0024).

    Ela vive no depósito, com prazo: passado o prazo, some. É de propósito —
    o arquivo é da pessoa, e guardar cópia dele aqui seria assumir uma
    responsabilidade que ninguém pediu. A resposta em texto continua na
    conversa para sempre.
    """

    def get(self, request, conversation_id, message_id):
        conversation = get_object_or_404(
            Conversation.objects.visiveis(), pk=conversation_id, user=request.user
        )
        pergunta = get_object_or_404(
            Message, pk=message_id, conversation=conversation, direction=Message.Direction.INBOUND
        )
        dados = deposito.buscar(pergunta.anexo_resposta_token)
        if dados is None:
            return Response(
                {"error": "a planilha preenchida já expirou; peça de novo com o arquivo anexado"},
                status=status.HTTP_404_NOT_FOUND,
            )

        nome = pergunta.anexo_resposta_nome or "planilha.xlsx"
        tipo = CSV_CONTENT_TYPE if nome.lower().endswith(".csv") else XLSX
        http = HttpResponse(dados, content_type=tipo)
        http["Content-Disposition"] = f'attachment; filename="jarvis_preenchida_{slugify(Path(nome).stem)[:50]}{Path(nome).suffix}"'
        return http


class MessageMiniaturaView(APIView):
    """A prévia da imagem de uma pergunta (ADR-0024).

    Só a dona da conversa vê. Nunca muda depois de criada, então o navegador
    guarda pelo tempo que quiser — cada rolagem da conversa não refaz o
    download.
    """

    def get(self, request, conversation_id, message_id):
        conversation = get_object_or_404(
            Conversation.objects.visiveis(), pk=conversation_id, user=request.user
        )
        pergunta = get_object_or_404(
            Message.objects.only("anexo_miniatura"), pk=message_id, conversation=conversation
        )
        if not pergunta.anexo_miniatura:
            return Response({"error": "esta mensagem não tem imagem"}, status=status.HTTP_404_NOT_FOUND)
        http = HttpResponse(bytes(pergunta.anexo_miniatura), content_type="image/jpeg")
        http["Cache-Control"] = "private, max-age=31536000, immutable"
        return http
