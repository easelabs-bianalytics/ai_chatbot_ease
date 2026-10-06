from django.contrib import admin
from django.utils import timezone

from ai_orchestrator.models import AICall, AIReply, CatalogGap, ReinicioDeLimite
from datasource.models import QueryRun


class ReadOnlyInline(admin.TabularInline):
    """Auditoria é para ler, não para editar: a trilha perde valor se alguém
    puder ajustá-la depois do fato."""

    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AICallInline(ReadOnlyInline):
    model = AICall
    fields = ("stage", "model", "tokens_input", "tokens_output", "cost_estimate", "latency_ms")


class QueryRunInline(ReadOnlyInline):
    model = QueryRun
    fields = (
        "attempt",
        "reference_query_id",
        "guard_result",
        "status",
        "row_count",
        "truncated",
        "duration_ms",
        "sql",
    )


@admin.register(AIReply)
class AIReplyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "message",
        "decision",
        "rule",
        "prompt_version",
        "tokens_input",
        "tokens_output",
        "cost_estimate",
        "latency_ms",
        "created_at",
    )
    list_filter = ("decision", "prompt_version", "created_at")
    search_fields = ("reply_text", "rule", "catalog_hash")
    inlines = (AICallInline, QueryRunInline)


@admin.register(CatalogGap)
class CatalogGapAdmin(admin.ModelAdmin):
    """Fila de trabalho do time de BI: cada lacuna é uma pergunta que o
    catálogo ainda não cobre."""

    list_display = ("id", "question", "status", "created_at", "resolved_at")
    list_filter = ("status", "created_at")
    search_fields = ("question", "reason")
    actions = ("marcar_como_resolvida",)

    @admin.action(description="Marcar lacunas selecionadas como resolvidas")
    def marcar_como_resolvida(self, request, queryset):
        total = queryset.update(status=CatalogGap.Status.RESOLVED, resolved_at=timezone.now())
        self.message_user(request, f"{total} lacuna(s) marcada(s) como resolvida(s).")


@admin.register(ReinicioDeLimite)
class ReinicioDeLimiteAdmin(admin.ModelAdmin):
    """A trilha dos reinícios de cota. Reiniciar é pela lista de usuários;
    aqui só se lê."""

    list_display = ("user", "feito_em", "feito_por")
    search_fields = ("user__email", "feito_por__email")
    date_hierarchy = "feito_em"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
