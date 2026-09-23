from django.urls import path

from whatsapp.views import WebhookView

urlpatterns = [
    path("webhook/<str:token>/", WebhookView.as_view(), name="whatsapp-webhook"),
]
