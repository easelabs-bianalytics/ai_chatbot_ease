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

    class Canal(models.TextChoices):
        WEB = "web", "Chat web"
        WHATSAPP = "whatsapp", "WhatsApp"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations"
    )
    title = models.CharField(max_length=200, blank=True)
    # Onde a conversa nasceu (ADR-0028). A do WhatsApp aparece também no chat
    # web, com o mesmo histórico; `whatsapp_jid` é o chat (pessoa ou grupo)
    # para onde a resposta volta.
    # `db_default`: o container antigo, que não conhece a coluna, continua
    # gravando entre o `migrate` e a troca da imagem.
    canal = models.CharField(max_length=20, choices=Canal.choices, default=Canal.WEB, db_default=Canal.WEB)
    whatsapp_jid = models.CharField(max_length=80, blank=True, db_index=True, db_default="")
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
    # Ordem escolhida à mão, arrastando na lista. Zero é "nunca foi
    # posicionada": a conversa nova nasce assim e aparece no topo, acima do
    # que já foi arrumado, sem que ninguém precise reordenar de novo a cada
    # pergunta. Quem arrasta recebe 1, 2, 3… na ordem em que ficou na tela.
    position = models.IntegerField(default=0)
    # Exclusão lógica (ADR-0018): some da tela do usuário, mas a pergunta, a
    # consulta executada e o custo continuam na auditoria (FR-15). Apagar de
    # verdade é decisão da política de retenção (O-08), não de um clique.
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ConversationQuerySet.as_manager()

    class Meta:
        # A ordem da mão vem primeiro; o resto continua pela última atividade.
        # Com todas em `position = 0` — o estado até alguém arrastar — isto é
        # exatamente o comportamento antigo.
        ordering = ["position", "-updated_at"]
        verbose_name = "conversa"
        verbose_name_plural = "conversas"

    def __str__(self):
        return f"Conversa #{self.pk} de {self.user}"
