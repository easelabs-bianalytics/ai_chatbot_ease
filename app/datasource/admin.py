from django.contrib import admin

from datasource.models import QueryRun


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
