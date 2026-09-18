"""Relatório de uso do Jarvis (FR-16).

Responde as perguntas que o time de BI faz sobre a ferramenta, e não sobre o
negócio: quanto se usou, quanto se gastou, quantas perguntas saíram com
número, onde o assistente disse que não sabe e o que demorou.

Tudo sai da auditoria que já existe (FR-15) — nenhuma tabela nova, nenhum
contador incrementado na hora da resposta. Contador paralelo diverge do
registro na primeira falha de gravação, e aí ninguém sabe qual dos dois
acreditar.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from ai_orchestrator.models import AICall, AIReply, CatalogGap
from datasource.models import DataExport, QueryRun
from messaging.models import Message

# Rótulos em português para a tela; a chave é o valor gravado no banco.
DECISOES = {
    AIReply.Decision.ANSWERED: "Respondeu com dado",
    AIReply.Decision.EMPTY_RESULT: "Consulta sem linhas",
    AIReply.Decision.CONVERSATION: "Conversa, sem consulta",
    AIReply.Decision.CLARIFY: "Pediu esclarecimento",
    AIReply.Decision.UNKNOWN: "Não sabe",
    AIReply.Decision.OUT_OF_SCOPE: "Fora de escopo",
    AIReply.Decision.FAILED: "Falhou",
}


@dataclass(frozen=True)
class Dia:
    data: str
    perguntas: int
    com_dado: int
    custo: Decimal


@dataclass(frozen=True)
class Lacuna:
    data: str
    pergunta: str
    motivo: str


@dataclass(frozen=True)
class Relatorio:
    inicio: datetime
    fim: datetime
    perguntas: int
    pessoas: int
    conversas: int
    decisoes: dict = field(default_factory=dict)
    custo: Decimal = Decimal("0")
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_em_cache: int = 0
    latencias: tuple = ()          # ordenadas, em ms
    consultas: int = 0
    consultas_corrigidas: int = 0
    consultas_com_erro: int = 0
    consultas_estouradas: int = 0
    reescritas: int = 0
    regras: dict = field(default_factory=dict)
    lacunas_abertas: int = 0
    lacunas: tuple = ()
    planilhas: int = 0
    por_dia: tuple = ()

    @property
    def taxa_de_cache(self) -> float:
        """Fatia da entrada que veio do cache do provedor, e custa um décimo.

        É o indicador que diz se vale mexer na ordem do contexto: prefixo
        estável no começo do prompt vira desconto direto."""
        return self.tokens_em_cache / self.tokens_entrada if self.tokens_entrada else 0.0

    @property
    def com_dado(self) -> int:
        return self.decisoes.get(AIReply.Decision.ANSWERED, 0)

    @property
    def taxa_com_dado(self) -> float:
        """Fatia das perguntas que terminou em número.

        Não é uma nota: "pediu esclarecimento" e "não sei" são respostas
        corretas em muitos casos. A taxa serve para perceber mudança de
        patamar entre um mês e outro."""
        return self.com_dado / self.perguntas if self.perguntas else 0.0

    @property
    def falhas(self) -> int:
        return self.decisoes.get(AIReply.Decision.FAILED, 0)

    @property
    def custo_por_pergunta(self) -> Decimal:
        if not self.perguntas:
            return Decimal("0")
        return (self.custo / self.perguntas).quantize(Decimal("0.0001"))

    @property
    def custo_projetado_mes(self) -> Decimal:
        """O que o ritmo atual daria em 30 dias, para comparar com o teto."""
        dias = max((self.fim - self.inicio).days, 1)
        return (self.custo / dias * 30).quantize(Decimal("0.01"))

    def percentil(self, p: float) -> int:
        if not self.latencias:
            return 0
        i = min(int(round(p * (len(self.latencias) - 1))), len(self.latencias) - 1)
        return self.latencias[i]


def montar_relatorio(inicio=None, fim=None, dias: int = 30) -> Relatorio:
    """Agrega a auditoria do período. `fim` é exclusivo."""
    fim = fim or timezone.now()
    inicio = inicio or (fim - timedelta(days=dias))
    intervalo = {"created_at__gte": inicio, "created_at__lt": fim}

    respostas = AIReply.objects.filter(**intervalo)
    perguntas = respostas.count()

    decisoes = {
        linha["decision"]: linha["n"]
        for linha in respostas.values("decision").annotate(n=Count("id"))
    }
    regras = {
        linha["rule"]: linha["n"]
        for linha in respostas.exclude(rule="").values("rule").annotate(n=Count("id")).order_by("-n")
    }

    totais = respostas.aggregate(
        custo=Sum("cost_estimate"),
        entrada=Sum("tokens_input"),
        saida=Sum("tokens_output"),
    )

    # A latência do que interessa: pergunta que foi ao banco. Conversa e
    # recusa respondem em dois segundos e puxariam o p95 para baixo.
    latencias = tuple(sorted(
        respostas.filter(
            decision__in=[AIReply.Decision.ANSWERED, AIReply.Decision.EMPTY_RESULT],
            latency_ms__isnull=False,
        ).values_list("latency_ms", flat=True)
    ))

    em_cache = sum(
        (r or {}).get("tokens_em_cache", 0) or 0
        for r in AICall.objects.filter(ai_reply__in=respostas).values_list("response", flat=True)
    )

    consultas = QueryRun.objects.filter(ai_reply__in=respostas)
    contagem_consultas = consultas.aggregate(
        total=Count("id"),
        corrigidas=Count("id", filter=Q(attempt__gt=1)),
        erros=Count("id", filter=Q(status=QueryRun.Status.ERROR)),
        estouradas=Count("id", filter=Q(status=QueryRun.Status.TIMEOUT)),
    )

    # Reescrita = a redação citou número sem suporte e teve de refazer
    # (ADR-0010). É o indicador mais direto de alucinação barrada.
    reescritas = (
        AICall.objects.filter(ai_reply__in=respostas, stage=AICall.Stage.REWRITE)
        .values("ai_reply_id").distinct().count()
    )

    mensagens = Message.objects.filter(
        direction=Message.Direction.INBOUND, created_at__gte=inicio, created_at__lt=fim
    )
    pessoas = mensagens.values("conversation__user_id").distinct().count()
    conversas = mensagens.values("conversation_id").distinct().count()

    lacunas = CatalogGap.objects.filter(**intervalo).order_by("-id")
    abertas = lacunas.filter(status=CatalogGap.Status.OPEN)

    return Relatorio(
        inicio=inicio,
        fim=fim,
        perguntas=perguntas,
        pessoas=pessoas,
        conversas=conversas,
        decisoes=decisoes,
        custo=totais["custo"] or Decimal("0"),
        tokens_entrada=totais["entrada"] or 0,
        tokens_saida=totais["saida"] or 0,
        tokens_em_cache=em_cache,
        latencias=latencias,
        consultas=contagem_consultas["total"],
        consultas_corrigidas=contagem_consultas["corrigidas"],
        consultas_com_erro=contagem_consultas["erros"],
        consultas_estouradas=contagem_consultas["estouradas"],
        reescritas=reescritas,
        regras=regras,
        lacunas_abertas=abertas.count(),
        lacunas=tuple(
            Lacuna(
                data=timezone.localtime(g.created_at).strftime("%d/%m"),
                pergunta=" ".join(g.question.split())[:90],
                motivo=" ".join((g.reason or "").split())[:90],
            )
            for g in abertas[:15]
        ),
        planilhas=DataExport.objects.filter(
            status=DataExport.Status.OK, created_at__gte=inicio, created_at__lt=fim
        ).count(),
        por_dia=_por_dia(respostas),
    )


def _por_dia(respostas) -> tuple:
    """Série diária.

    O agrupamento é feito em Python, no fuso local: agrupar no banco por
    `date(created_at)` daria o dia em UTC, e toda pergunta feita depois das
    21h cairia no dia seguinte."""
    acumulado = {}
    for r in respostas.values_list("created_at", "decision", "cost_estimate"):
        criado, decisao, custo = r
        dia = timezone.localtime(criado).date()
        atual = acumulado.setdefault(dia, [0, 0, Decimal("0")])
        atual[0] += 1
        atual[1] += 1 if decisao == AIReply.Decision.ANSWERED else 0
        atual[2] += custo or Decimal("0")
    return tuple(
        Dia(data=dia.strftime("%d/%m/%Y"), perguntas=n, com_dado=c, custo=v)
        for dia, (n, c, v) in sorted(acumulado.items())
    )
