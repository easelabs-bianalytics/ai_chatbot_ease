from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """Uma thread de chat de um usuário interno.

    No projeto de referência a conversa pertencia a um contato de WhatsApp.
    Aqui o dono é um usuário autenticado (ADR-0011), e cada um enxerga apenas
    as próprias conversas.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        ARCHIVED = "archived", "Arquivada"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations"
    )
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "conversa"
        verbose_name_plural = "conversas"

    def __str__(self):
        return f"Conversa #{self.pk} de {self.user}"
