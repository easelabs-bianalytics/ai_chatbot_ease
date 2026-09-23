from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from whatsapp.models import ContatoWhatsApp, EnvioWhatsApp, GrupoWhatsApp


@admin.register(ContatoWhatsApp)
class ContatoWhatsAppAdmin(admin.ModelAdmin):
    """Quem pode falar com o Jarvis no individual. Número fora daqui é
    ignorado em silêncio."""

    list_display = ("numero", "user", "ativo", "observacao", "created_at")
    list_filter = ("ativo",)
    search_fields = ("numero", "user__username", "user__email", "observacao")
    autocomplete_fields = ("user",)

    def changelist_view(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), "subtitle": format_html(
            'Estado do número e QR para parear: <a href="{}">Conexão do WhatsApp</a>', reverse("whatsapp-conexao"))}
        return super().changelist_view(request, extra_context)


@admin.register(GrupoWhatsApp)
class GrupoWhatsAppAdmin(admin.ModelAdmin):
    """Grupos em que o Jarvis responde quando marcado. Liberar um grupo é
    decidir que todos os membros veem dados de negócio (ADR-0028)."""

    list_display = ("nome", "jid", "ativo", "limite_diario", "limite_semanal", "created_at")
    list_filter = ("ativo",)
    search_fields = ("nome", "jid")


@admin.register(EnvioWhatsApp)
class EnvioWhatsAppAdmin(admin.ModelAdmin):
    list_display = ("externo_id", "tipo", "jid", "message", "created_at")
    list_filter = ("tipo",)
    search_fields = ("externo_id", "jid")
    readonly_fields = ("message", "externo_id", "jid", "tipo", "created_at")
