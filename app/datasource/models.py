from django.db import models

from ai_orchestrator.models import AIReply


class QueryRun(models.Model):
    """Uma tentativa de consulta ao banco de negócio.

    É o que sustenta a regra "nenhum número sem consulta registrada"
    (ADR-0010): o SQL exato que rodou, se o validador aprovou, quanto tempo
    levou e o que voltou. Uma linha por tentativa, porque a correção única
    (ADR-0014) gera uma segunda — e a tentativa reprovada é justamente a que
    interessa quando alguém for entender o que aconteceu.

    A Fase 2 cria só o modelo; o executor é da Fase 3.
    """

    class GuardResult(models.TextChoices):
        APPROVED = "approved", "Aprovada pelo validador"
        REJECTED = "rejected", "Recusada pelo validador"

    class Status(models.TextChoices):
        NOT_EXECUTED = "not_executed", "Não executada"
        SUCCESS = "success", "Executada"
        ERROR = "error", "Erro do banco"
        TIMEOUT = "timeout", "Tempo esgotado"

    ai_reply = models.ForeignKey(AIReply, on_delete=models.CASCADE, related_name="query_runs")
    attempt = models.PositiveSmallIntegerField(default=1)
    sql = models.TextField()
    # Qxx de chatbot_bi_referencia_querys.md usada como base, quando houve.
    reference_query_id = models.CharField(max_length=20, blank=True)
    guard_result = models.CharField(max_length=20, choices=GuardResult.choices)
    guard_reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_EXECUTED)
    row_count = models.PositiveIntegerField(null=True, blank=True)
    truncated = models.BooleanField(default=False)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)
    result_sample = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "consulta executada"
        verbose_name_plural = "consultas executadas"

    def __str__(self):
        return f"Consulta #{self.pk} (tentativa {self.attempt}, {self.status})"


class DataExport(models.Model):
    """Um download de planilha (ADR-0020).

    A planilha roda a consulta de novo, com limite maior que o da conversa,
    e pode levar milhares de linhas para fora da aplicação. Por isso cada
    download fica registrado: quem, de qual resposta, qual consulta, quantas
    linhas e quando."""

    class Status(models.TextChoices):
        OK = "ok", "Gerada"
        ERROR = "error", "Falhou"

    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, related_name="data_exports"
    )
    message = models.ForeignKey(
        "messaging.Message", on_delete=models.SET_NULL, null=True, related_name="exports"
    )
    sql = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices)
    row_count = models.PositiveIntegerField(null=True, blank=True)
    truncated = models.BooleanField(default=False)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "planilha exportada"
        verbose_name_plural = "planilhas exportadas"

    def __str__(self):
        return f"Exportação #{self.pk} ({self.status})"
