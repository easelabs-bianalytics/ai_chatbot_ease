from django.urls import path

from messaging.views import (
    ConversationDetailView,
    ConversationListCreateView,
    ConversationOrderView,
    MessageExcelView,
    MessageListCreateView,
    ProjectDetailView,
    ProjectListCreateView,
)

urlpatterns = [
    path("conversations/", ConversationListCreateView.as_view(), name="conversations"),
    # Antes da rota com <int:...> por clareza; "ordem" nunca casaria com ela.
    path("conversations/ordem/", ConversationOrderView.as_view(), name="conversation-order"),
    path(
        "conversations/<int:conversation_id>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path(
        "conversations/<int:conversation_id>/messages/",
        MessageListCreateView.as_view(),
        name="conversation-messages",
    ),
    path(
        "conversations/<int:conversation_id>/messages/<int:message_id>/excel/",
        MessageExcelView.as_view(),
        name="message-excel",
    ),
    path("projects/", ProjectListCreateView.as_view(), name="projects"),
    path("projects/<int:project_id>/", ProjectDetailView.as_view(), name="project-detail"),
]
