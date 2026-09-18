from django.contrib import admin

from datasource.models import DataExport, QueryRun


@admin.register(QueryRun)
class QueryRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ai_reply",
        "attempt",
        "reference_query_id",
        "guard_result",
        "status",
        "row_count",
        "truncated",
        "duration_ms",
        "created_at",
    )
    list_filter = ("guard_result", "status", "truncated", "created_at")
    search_fields = ("sql", "reference_query_id", "error")


@admin.register(DataExport)
class DataExportAdmin(admin.ModelAdmin):
    """Quem baixou o quê: cada planilha leva dados para fora da aplicação."""

    list_display = ("id", "user", "message", "status", "row_count", "truncated", "duration_ms", "created_at")
    list_filter = ("status", "truncated", "created_at")
    search_fields = ("user__username", "sql", "error")
    readonly_fields = [f.name for f in DataExport._meta.fields]

    def has_add_permission(self, request):
        return False
