from django.contrib import admin

from messaging.models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "direction", "status", "content", "created_at")
    list_filter = ("direction", "status", "created_at")
    search_fields = ("content", "client_message_id")
