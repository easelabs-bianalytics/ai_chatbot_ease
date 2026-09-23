from django.db import models

from messaging.models import Message


class AIReply(models.Model):
    """O que o sistema decidiu para uma pergunta, e quanto custou.

    Uma linha por pergunta processada (FR-15). É o registro que sustenta a
    auditoria no Admin e o relatório: sem ele não dá para saber por que uma
    resposta saiu daquele jeito, nem quanto custou produzi-la.

    A Fase 2 cria só o modelo; quem preenche é o orquestrador (Fase 4).
    """

    class Decision(models.TextChoices):
        ANSWERED = "answered", "Respondeu com dado"
        EMPTY_RESULT = "empty_result", "Consulta sem linhas"
        CLARIFY = "clarify", "Pediu esclarecimento"
        UNKNOWN = "unknown", "Não sabe"
        OUT_OF_SCOPE = "out_of_scope", "Fora de escopo"
        CONVERSATION = "conversation", "Conversa sem consulta"
        # Leitura de imagem anexada (ADR-0024): a única decisão em que a
        # resposta NÃO passou pelo banco. Fica separada justamente para o
        # relatório e a auditoria não confundirem as duas coisas.
        IMAGE_READING = "image_reading", "Leitura de imagem"
        FAILED = "failed", "Falha da IA ou do banco"
        # Interrompida pela pessoa. Fica como decisão própria para o
        # relatório não contar como falha nossa o que foi escolha de quem
        # perguntou — e para o custo já gasto aparecer mesmo assim.
        CANCELLED = "cancelled", "Interrompida pelo usuário"

    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name="ai_reply")
    decision = models.CharField(max_length=20, choices=Decision.choices)
    # Preenchido quando a resposta veio de regra determinística, sem IA
    # (pedido de escrita, ajuda, mensagem inválida).
    rule = models.CharField(max_length=60, blank=True)
    reply_text = models.TextField(blank=True)
    prompt_version = models.CharField(max_length=50, blank=True)
    # SHA-256 das referências + catálogo: diz com que conhecimento a resposta
    # foi produzida (ADR-0006).
    catalog_hash = models.CharField(max_length=64, blank=True)
    tokens_input = models.PositiveIntegerField(null=True, blank=True)
    tokens_output = models.PositiveIntegerField(null=True, blank=True)
    cost_estimate = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "resposta da IA"
        verbose_name_plural = "respostas da IA"

    def __str__(self):
        return f"Resposta da mensagem #{self.message_id} ({self.decision})"


class AICall(models.Model):
    """Uma chamada ao modelo dentro de uma resposta.

    São várias por resposta (planejar, corrigir a consulta, redigir,
    reescrever), e por isso ficam separadas do AIReply: sem elas não dá para
    ver qual etapa gastou o quê nem o que o modelo devolveu em cada uma.
    """

    class Stage(models.TextChoices):
        PLAN = "plan", "Planejamento"
        FIX = "fix", "Correção da consulta"
        ANSWER = "answer", "Redação"
        REWRITE = "rewrite", "Reescrita da resposta"
        IMAGE = "image", "Leitura de imagem"
        # Rodada de aprofundamento de uma investigação (ADR-0025): o
        # planejador lê os achados e decide o próximo ramo.
        INVESTIGATE = "investigate", "Rodada de investigação"

    ai_reply = models.ForeignKey(AIReply, on_delete=models.CASCADE, related_name="calls")
    stage = models.CharField(max_length=20, choices=Stage.choices)
    model = models.CharField(max_length=100)
    tokens_input = models.PositiveIntegerField(null=True, blank=True)
    tokens_output = models.PositiveIntegerField(null=True, blank=True)
    cost_estimate = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    request = models.JSONField(default=dict, blank=True)
    response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "chamada ao modelo"
        verbose_name_plural = "chamadas ao modelo"

    def __str__(self):
        return f"{self.get_stage_display()} ({self.model})"


class CatalogGap(models.Model):
    """Pergunta que o sistema não soube responder.

    Existe para que "não sei" não seja um beco sem saída: cada uma vira item
    do backlog do catálogo para o time de BI (ADR-0010, ADR-0014).
    """

    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        RESOLVED = "resolved", "Resolvida"

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="catalog_gaps")
    question = models.TextField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "lacuna do catálogo"
        verbose_name_plural = "lacunas do catálogo"

    def __str__(self):
        return f"Lacuna #{self.pk}: {self.question[:60]}"
