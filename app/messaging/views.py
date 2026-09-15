"""API do chat (ADR-0007). Tudo exige login (ADR-0011)."""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from conversations.models import Conversation
from messaging.channels.web import WebChannel
from messaging.services import ingest_inbound_message

_channel = WebChannel()


def _conversation_json(conversation):
    return {
        "id": conversation.pk,
        "title": conversation.title,
        "status": conversation.status,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def _message_json(message):
    return {
        "id": message.pk,
        "direction": message.direction,
        "text": message.content,
        "status": message.status,
        "created_at": message.created_at.isoformat(),
    }


class ConversationListCreateView(APIView):
    def get(self, request):
        conversations = Conversation.objects.filter(user=request.user)
        return Response({"conversations": [_conversation_json(c) for c in conversations]})

    def post(self, request):
        title = str(request.data.get("title") or "").strip()[:200]
        conversation = Conversation.objects.create(user=request.user, title=title)
        return Response(_conversation_json(conversation), status=status.HTTP_201_CREATED)


class MessageListCreateView(APIView):
    """Mensagens de uma conversa.

    A conversa é sempre buscada com `user=request.user`: pedir a de outra
    pessoa devolve 404, e não 403, para não confirmar que ela existe.
    """

    def _conversation(self, request, conversation_id):
        return get_object_or_404(Conversation, pk=conversation_id, user=request.user)

    def get(self, request, conversation_id):
        conversation = self._conversation(request, conversation_id)
        messages = conversation.messages.all()

        # O navegador busca só o que chegou depois do que ele já tem.
        after = request.query_params.get("after")
        if after:
            try:
                messages = messages.filter(id__gt=int(after))
            except ValueError:
                return Response(
                    {"error": "parâmetro after inválido"}, status=status.HTTP_400_BAD_REQUEST
                )

        return Response({"messages": [_message_json(m) for m in messages]})

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

        if not created:
            return Response(
                {
                    "message_id": message.pk,
                    "conversation_id": conversation.pk,
                    "created": False,
                },
                status=status.HTTP_200_OK,
            )

        # Fase 4: aqui entra o enfileiramento da tarefa que planeja, consulta
        # e responde (ADR-0003). Por ora a pergunta só fica registrada, e a
        # resposta aparece no polling quando o orquestrador existir.
        return Response(
            {
                "message_id": message.pk,
                "conversation_id": conversation.pk,
                "created": True,
                "status": "queued",
            },
            status=status.HTTP_202_ACCEPTED,
        )
