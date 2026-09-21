"""Controle de quem usa o Jarvis.

Usuários: quem já entrou, quando entrou pela primeira e pela última vez, e o
botão que importa — desativar. Usuário desativado não recebe mais código,
mesmo tendo e-mail da empresa.

Códigos de acesso: a trilha de cada pedido. Só leitura: a trilha não se edita.
"""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from web.models import CodigoDeAcesso

Usuario = get_user_model()


admin.site.site_header = "Jarvis · Administração"
admin.site.site_title = "Jarvis"
admin.site.index_title = "Controle do Jarvis"


admin.site.unregister(Usuario)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("email", "first_name", "last_name", "is_active", "is_staff", "date_joined", "last_login")
    list_filter = ("is_active", "is_staff", "groups")
    search_fields = ("email", "first_name", "last_name", "username")
    ordering = ("-last_login",)
    readonly_fields = ("date_joined", "last_login")


@admin.register(CodigoDeAcesso)
class CodigoDeAcessoAdmin(admin.ModelAdmin):
    list_display = ("email", "criado_em", "situacao", "tentativas", "ip")
    list_filter = ("criado_em",)
    search_fields = ("email", "ip")
    date_hierarchy = "criado_em"
    # O hash fica de fora da tela: não serve para nada a quem olha.
    fields = ("email", "criado_em", "expira_em", "usado_em", "anulado_em", "tentativas", "ip", "navegador")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
