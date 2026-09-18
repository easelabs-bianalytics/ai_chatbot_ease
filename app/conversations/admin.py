from django.contrib import admin

from conversations.models import Conversation, Project


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "project", "status", "deleted_at", "updated_at")
    list_filter = ("status", ("deleted_at", admin.EmptyFieldListFilter), "created_at")
    search_fields = ("title", "user__username", "user__email")
    date_hierarchy = "created_at"


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "user", "created_at")
    search_fields = ("name", "user__username")
