from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from whatsapp.models import ContatoWhatsApp, EnvioWhatsApp, GrupoWhatsApp


@admin.register(ContatoWhatsApp)
class ContatoWhatsAppAdmin(admin.ModelAdmin):
    """Quem pode falar com o Jarvis no individual. Número fora daqui é
    ignorado em silêncio."""

    list_display = ("numero", "nome", "user", "ativo", "observacao", "created_at")
    list_filter = ("ativo",)
    search_fields = ("numero", "nome", "user__username", "user__email", "observacao")
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


# A página de conexão é uma view solta (whatsapp.views.conexao), e o Admin só
# lista modelos. Em 2026-09-24 ela não aparecia na seção WhatsApp e só se
# chegava pelo link: esta linha a põe lá, no topo da seção.
_lista_original = admin.site.get_app_list


def _lista_com_conexao(request, app_label=None):
    lista = _lista_original(request, app_label)
    for app in lista:
        if app.get("app_label") == "whatsapp":
            app["models"].insert(0, {
                "name": "Conexão do WhatsApp", "object_name": "Conexao",
                "admin_url": reverse("whatsapp-conexao"), "add_url": None,
                "view_only": True, "perms": {"view": True},
            })
    return lista


admin.site.get_app_list = _lista_com_conexao
