import logging
from pathlib import Path

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.text import slugify

from attachments import deposito

from messaging.models import ArquivoDaConversa, Avaliacao, Message

logger = logging.getLogger(__name__)


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


# Tipo do arquivo pela extensão do nome original: no S3 ele se chama só pelo
# token, sem extensão.
_TIPOS = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".csv": "text/csv; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@admin.register(ArquivoDaConversa)
class ArquivoDaConversaAdmin(admin.ModelAdmin):
    """Os arquivos guardados por conversa (ADR-0034), para auditoria.

    Dá para baixar cada um, com o nome original, mas não para criar nem
    apagar: apagar é apagar a conversa, que apaga os arquivos dela no S3. As
    planilhas trazem CRM de médico e, às vezes, CPF de paciente — por isso só
    quem tem permissão de ver estes registros baixa, e cada download fica no
    log com quem baixou e o quê."""

    list_display = ("id", "conversation", "papel", "nome", "tamanho", "created_at", "baixar")
    list_filter = ("papel", "created_at")
    search_fields = ("nome", "token", "conversation__title")
    readonly_fields = ("conversation", "message", "token", "papel", "nome", "tamanho", "chave", "created_at",
                       "baixar")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        rotas = [
            path(
                "<int:arquivo_id>/baixar/",
                self.admin_site.admin_view(self.baixar_arquivo),
                name="messaging_arquivodaconversa_baixar",
            ),
        ]
        return rotas + super().get_urls()

    @admin.display(description="arquivo")
    def baixar(self, obj):
        if obj.pk is None:
            return ""
        return format_html('<a href="{}">Baixar</a>',
                           reverse("admin:messaging_arquivodaconversa_baixar", args=[obj.pk]))

    def baixar_arquivo(self, request, arquivo_id):
        arquivo = get_object_or_404(ArquivoDaConversa, pk=arquivo_id)
        if not self.has_view_permission(request, arquivo):
            raise PermissionDenied
        dados = deposito.buscar(arquivo.token)
        if dados is None:
            # Passou dos dois anos (o ciclo de vida do bucket apagou) ou o S3
            # não respondeu: diz isso, em vez de devolver arquivo vazio.
            self.message_user(request, f"O arquivo \"{arquivo.nome}\" não está mais disponível.",
                              level=messages.WARNING)
            return redirect("admin:messaging_arquivodaconversa_changelist")
        logger.info("Admin: %s baixou o arquivo %s (%s) da conversa %s",
                    request.user, arquivo.pk, arquivo.nome, arquivo.conversation_id)
        nome = arquivo.nome or "arquivo"
        sufixo = Path(nome).suffix.lower()
        http = HttpResponse(dados, content_type=_TIPOS.get(sufixo, "application/octet-stream"))
        http["Content-Disposition"] = f'attachment; filename="{slugify(Path(nome).stem)[:60] or "arquivo"}{sufixo}"'
        return http
