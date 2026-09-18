from django.conf import settings
from django.db import models


class Project(models.Model):
    """Pasta que o usuário cria para agrupar conversas de um mesmo assunto
    ("Fechamento de agosto", "Território Sul").

    É só organização da lista: não muda o que a IA sabe nem o contexto das
    perguntas — cada conversa continua sendo um assunto próprio.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "projeto"
        verbose_name_plural = "projetos"

    def __str__(self):
        return f"{self.name} ({self.user})"


class ConversationQuerySet(models.QuerySet):
    def visiveis(self):
        """O que o usuário vê: tudo menos o que ele excluiu."""
        return self.filter(deleted_at__isnull=True)


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
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        # Excluir a pasta devolve as conversas para a lista geral; apagar
        # conversa junto com a pasta surpreenderia quem só quis reorganizar.
        on_delete=models.SET_NULL,
        related_name="conversations",
    )
    # Exclusão lógica (ADR-0018): some da tela do usuário, mas a pergunta, a
    # consulta executada e o custo continuam na auditoria (FR-15). Apagar de
    # verdade é decisão da política de retenção (O-08), não de um clique.
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ConversationQuerySet.as_manager()

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "conversa"
        verbose_name_plural = "conversas"

    def __str__(self):
        return f"Conversa #{self.pk} de {self.user}"
