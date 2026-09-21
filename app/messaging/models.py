import uuid

from django.db import models

from conversations.models import Conversation


def new_outbound_id() -> str:
    """Identificador das mensagens que o sistema envia; a do usuário vem do
    navegador."""
    return f"out-{uuid.uuid4()}"


class Message(models.Model):
    """Uma pergunta do usuário ou uma resposta do sistema.

    `client_message_id` é a chave de idempotência (FR-02): o navegador gera um
    por pergunta, e clique duplo ou reenvio por falha de rede devolve a
    mensagem que já existe em vez de processar de novo.

    A unicidade é por conversa, e não global como na referência: dois clientes
    podem gerar o mesmo identificador por bug ou por acaso, e isso não pode
    fazer um usuário receber a resposta do outro.
    """

    class Direction(models.TextChoices):
        INBOUND = "in", "Pergunta"
        OUTBOUND = "out", "Resposta"

    class Anexo(models.TextChoices):
        PLANILHA = "planilha", "Planilha"
        IMAGEM = "imagem", "Imagem"

    class Status(models.TextChoices):
        RECEIVED = "received", "Recebida"
        PROCESSING = "processing", "Em processamento"
        PROCESSED = "processed", "Processada"
        SENT = "sent", "Entregue"
        FAILED = "failed", "Falhou"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)
    content = models.TextField()
    client_message_id = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED)
    delivery_detail = models.TextField(blank=True)
    # Resposta → pergunta que a gerou. É o que permite à interface mostrar a
    # fonte embaixo da resposta (SQL, referência, momento): a auditoria mora
    # no AIReply da pergunta, e sem este vínculo a resposta seria só texto.
    in_reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replies",
    )
    # Anexo (ADR-0024). O arquivo NÃO fica aqui e não fica em lugar nenhum:
    # os bytes vivem no depósito com prazo (`attachments/deposito.py`) e são
    # descartados depois da resposta. Da mensagem guardamos o que a conversa
    # precisa mostrar depois e o que a auditoria precisa saber: o tipo, o
    # nome e o resumo que efetivamente subiu ao modelo.
    anexo_tipo = models.CharField(max_length=10, choices=Anexo.choices, blank=True)
    anexo_nome = models.CharField(max_length=255, blank=True)
    anexo_resumo = models.TextField(blank=True)
    # Token do depósito, para o worker achar os bytes. Vence junto com eles;
    # guardado por ser só uma chave, nunca conteúdo.
    anexo_token = models.CharField(max_length=64, blank=True)
    # Prévia da imagem na conversa: JPEG de até 480 px (poucos KB), feita na
    # hora da pergunta. É a única coisa do anexo que fica — a imagem que foi
    # ao modelo é descartada. Sem ela, o print sumiria da conversa no F5.
    anexo_miniatura = models.BinaryField(null=True, blank=True, editable=False)
    # Token da planilha PREENCHIDA, para o botão de baixar. Também vence.
    anexo_resposta_token = models.CharField(max_length=64, blank=True)
    anexo_resposta_nome = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "mensagem"
        verbose_name_plural = "mensagens"
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "client_message_id"],
                name="unique_client_message_id_por_conversa",
            )
        ]
        indexes = [models.Index(fields=["conversation", "id"])]

    def __str__(self):
        return f"Mensagem #{self.pk} ({self.get_direction_display()})"
