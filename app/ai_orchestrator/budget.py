"""Teto de gasto mensal com a IA (O-14, ADR-0016).

O custo por pergunta é uma estimativa até o sistema rodar de verdade: ele
depende de quantas perguntas viram esclarecimento, de quantas consultas
precisam de correção e de quanto o cache do provedor ajuda. Estimativa
errada só aparece na fatura — e aparece no fim do mês.

Por isso o limite mora na aplicação: ela soma o que já gastou no mês (o
custo de cada resposta é registrado em `AIReply`) e para antes de estourar,
com uma mensagem honesta, em vez de continuar gastando.
"""

import datetime
import os
from decimal import Decimal

from django.db.models import Sum

from ai_orchestrator.models import AIReply

VARIAVEL = "AI_MONTHLY_BUDGET_USD"


def teto() -> Decimal | None:
    """Limite do mês em dólares, ou None quando não há limite configurado."""
    bruto = os.environ.get(VARIAVEL, "").strip()
    if not bruto:
        return None
    try:
        valor = Decimal(bruto.replace(",", "."))
    except (ArithmeticError, ValueError):
        return None
    return valor if valor > 0 else None


def gasto_do_mes(hoje: datetime.date | None = None) -> Decimal:
    hoje = hoje or datetime.date.today()
    primeiro = hoje.replace(day=1)
    total = AIReply.objects.filter(created_at__date__gte=primeiro).aggregate(
        total=Sum("cost_estimate")
    )["total"]
    return Decimal(total or 0)


def situacao(hoje: datetime.date | None = None) -> dict:
    limite = teto()
    gasto = gasto_do_mes(hoje)
    usado = float(gasto / limite) if limite else 0.0
    return {
        "teto": limite,
        "gasto": gasto,
        "fracao_usada": usado,
        "excedido": bool(limite and gasto >= limite),
        "perto_do_limite": bool(limite and 0.8 <= usado < 1.0),
    }


def excedido(hoje: datetime.date | None = None) -> bool:
    return situacao(hoje)["excedido"]
