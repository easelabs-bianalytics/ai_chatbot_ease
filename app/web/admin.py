"""Controle de quem usa o Jarvis.

Usuários: quem já entrou, quando entrou pela primeira e pela última vez, e o
botão que importa — desativar. Usuário desativado não recebe mais código,
mesmo tendo e-mail da empresa.

Códigos de acesso: a trilha de cada pedido. Só leitura: a trilha não se edita.

Limite de perguntas: a lista mostra quanto cada pessoa usou no dia e na
semana, e um superusuário reinicia a cota de quem chegou no limite.
"""

import logging

from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied

from ai_orchestrator import limites
from ai_orchestrator.models import ReinicioDeLimite
from web.models import CodigoDeAcesso

logger = logging.getLogger(__name__)

Usuario = get_user_model()


admin.site.site_header = "Jarvis · Administração"
admin.site.site_title = "Jarvis"
admin.site.index_title = "Controle do Jarvis"


admin.site.unregister(Usuario)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("email", "first_name", "last_name", "is_active", "is_staff", "cota", "date_joined", "last_login")
    list_filter = ("is_active", "is_staff", "groups")
    search_fields = ("email", "first_name", "last_name", "username")
    ordering = ("-last_login",)
    readonly_fields = ("date_joined", "last_login")
    actions = ["reiniciar_limite"]

    @admin.display(description="Perguntas (dia · semana)")
    def cota(self, obj):
        situacao = limites.situacao(obj)
        if situacao["dia"] is None:
            return "sem limite"
        dia, semana = situacao["dia"], situacao["semana"]
        texto = f"{dia['usadas']}/{dia['limite']} · {semana['usadas']}/{semana['limite']}"
        return f"{texto} (no limite)" if situacao["excedeu"] else texto

    def get_actions(self, request):
        # Só superusuário reinicia: é liberar gasto de IA, decisão de quem
        # administra o Jarvis, não de qualquer pessoa da equipe com acesso.
        acoes = super().get_actions(request)
        if not request.user.is_superuser:
            acoes.pop("reiniciar_limite", None)
        return acoes

    @admin.action(description="Reiniciar o limite de perguntas")
    def reiniciar_limite(self, request, queryset):
        """Zera a cota do dia e da semana dos usuários marcados (2026-10-06,
        a Larissa no limite). As respostas continuam na auditoria; a
        contagem passa a começar agora (`ReinicioDeLimite`)."""
        if not request.user.is_superuser:
            raise PermissionDenied
        pessoas = list(queryset)
        ReinicioDeLimite.objects.bulk_create(
            [ReinicioDeLimite(user=pessoa, feito_por=request.user) for pessoa in pessoas]
        )
        nomes = ", ".join(p.email or p.username for p in pessoas)
        logger.info("Admin: %s reiniciou o limite de perguntas de %s", request.user.email or request.user, nomes)
        self.message_user(request, f"Limite de perguntas reiniciado: {nomes}.", messages.SUCCESS)


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
