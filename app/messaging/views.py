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
from datasource.executors.factory import get_configured_executor
from messaging import fonte, planilha_da_resposta
from messaging.channels.web import WebChannel
from messaging.models import Avaliacao, Message
from messaging.services import ingest_inbound_message
from attachments import deposito
from attachments.receber import preparar_anexo
from attachments.limites import MAX_BYTES, AnexoRecusado

_channel = WebChannel()


def _conversation_json(conversation):
    return {
        "id": conversation.pk,
        "title": conversation.title,
        "status": conversation.status,
        "project": conversation.project_id,
        "position": conversation.position,
        # Conversa que veio do WhatsApp (ADR-0028): a lista marca, e a
        # resposta a uma pergunta feita aqui fica aqui.
        "canal": conversation.canal,
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


def _tem_avaliacao(message) -> bool:
    try:
        message.avaliacao
    except Avaliacao.DoesNotExist:
        return False
    return True


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
        # concentrada?") e o que ele entendeu do pedido, para a tela não
        # ficar em "Pensando…" por minutos.
        andamento = progresso.ler_tudo(message.pk)
        if andamento.get("texto"):
            dados["progresso"] = andamento["texto"]
            dados["etapa"] = andamento.get("etapa", "")
        if andamento.get("entendimento"):
            dados["entendimento"] = andamento["entendimento"]
    if message.direction == message.Direction.OUTBOUND:
        dados["in_reply_to"] = message.in_reply_to_id
        dados["fonte"] = fonte.montar(message, mostrar_custo)
        avaliacao = getattr(message, "avaliacao", None) if _tem_avaliacao(message) else None
        if avaliacao is not None:
            dados["avaliacao"] = {"nota": avaliacao.nota, "comentario": avaliacao.comentario}
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
            "in_reply_to__ai_reply", "avaliacao"
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


class MessageCancelView(APIView):
    """Interrompe uma pergunta que ainda está sendo respondida.

    Só escreve o status; quem para de fato é o worker, que o lê entre as
    etapas (`foi_interrompida`, no orquestrador). Não há nada a matar do
    lado do banco de negócio: consulta em curso termina sozinha em
    milissegundos e leitura no RDS não é cobrada por consulta.

    O `update` filtrado é a garantia contra a corrida: se a resposta acabou
    de ficar pronta, o status já não é mais "recebida" nem "em
    processamento", nenhuma linha muda e a resposta entregue continua
    valendo.
    """

    def post(self, request, conversation_id, message_id):
        conversation = get_object_or_404(
            Conversation.objects.visiveis(), pk=conversation_id, user=request.user
        )
        mensagem = get_object_or_404(
            conversation.messages, pk=message_id, direction=Message.Direction.INBOUND
        )
        interrompida = Message.objects.filter(
            pk=mensagem.pk,
            status__in=(Message.Status.RECEIVED, Message.Status.PROCESSING),
        ).update(status=Message.Status.CANCELLED)
        return Response({"interrompida": bool(interrompida)})


MAX_COMENTARIO = 2000


class MessageAvaliacaoView(APIView):
    """👍 ou 👎 numa resposta, com "o que estava errado" (opcional).

    PUT grava ou troca a avaliação; DELETE desfaz (clicar de novo no mesmo
    botão). Só quem é dono da conversa avalia, e só resposta do Jarvis que
    veio de uma pergunta — mensagem de outra pessoa dá 404."""

    def _resposta(self, request, conversation_id, message_id):
        conversation = get_object_or_404(
            Conversation.objects.visiveis(), pk=conversation_id, user=request.user
        )
        return get_object_or_404(
            conversation.messages, pk=message_id, direction=Message.Direction.OUTBOUND,
            in_reply_to__isnull=False,
        )

    def put(self, request, conversation_id, message_id):
        resposta = self._resposta(request, conversation_id, message_id)
        nota = str(request.data.get("nota") or "")
        if nota not in Avaliacao.Nota.values:
            return Response({"error": "nota deve ser up ou down"}, status=status.HTTP_400_BAD_REQUEST)
        comentario = " ".join(str(request.data.get("comentario") or "").split())[:MAX_COMENTARIO]
        avaliacao, _ = Avaliacao.objects.update_or_create(
            message=resposta,
            defaults={
                "nota": nota,
                # 👍 não leva comentário de 👎 antigo junto.
                "comentario": comentario if nota == Avaliacao.Nota.ERRADA else "",
                # Trocar de ideia depois da exportação faz o caso voltar à fila.
                "caso_exportado_em": None,
            },
        )
        return Response({"nota": avaliacao.nota, "comentario": avaliacao.comentario})

    def delete(self, request, conversation_id, message_id):
        resposta = self._resposta(request, conversation_id, message_id)
        Avaliacao.objects.filter(message=resposta).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        # `?consulta=N`: a planilha de uma tabela da resposta em blocos, com a
        # consulta DELA (resposta com várias consultas, 2026-09-25).
        indice = request.query_params.get("consulta")
        indice = int(indice) if indice not in (None, "") and str(indice).isdigit() else None
        planilha = planilha_da_resposta.gerar(resposta, request.user, get_configured_executor(), consulta=indice)
        if planilha.erro:
            return Response({"error": planilha.erro}, status=planilha.status)
        http = HttpResponse(planilha.conteudo, content_type=XLSX)
        http["Content-Disposition"] = f'attachment; filename="{planilha.nome}"'
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

        try:
            etiqueta = preparar_anexo((arquivo.name or "arquivo")[:255], arquivo.read())
        except AnexoRecusado as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(etiqueta, status=status.HTTP_201_CREATED)


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
