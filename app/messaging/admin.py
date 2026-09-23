from django.contrib import admin

from messaging.models import Avaliacao, Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "direction", "status", "content", "created_at")
    list_filter = ("direction", "status", "created_at")
    search_fields = ("content", "client_message_id")


@admin.register(Avaliacao)
class AvaliacaoAdmin(admin.ModelAdmin):
    """Onde o time de BI lê os 👎 antes de virar caso de validação."""

    list_display = ("id", "nota", "pergunta", "comentario", "created_at", "caso_exportado_em")
    list_filter = ("nota", "created_at", "caso_exportado_em")
    search_fields = ("comentario", "message__content", "message__in_reply_to__content")
    readonly_fields = ("message", "nota", "comentario", "created_at", "updated_at")

    @admin.display(description="pergunta")
    def pergunta(self, obj):
        anterior = obj.message.in_reply_to
        return (anterior.content[:80] if anterior else "")
