"""Saldo da conta da OpenAI, estimado, com aviso antes de acabar.

A OpenAI não tem API pública para ler o saldo pré-pago: quem sabe quanto
foi carregado é quem carregou. Até aqui a primeira notícia do saldo zerado
era a falha (`sem_creditos_na_ia`): a pessoa perguntava, recebia "estou sem
créditos", e só então alguém ia recarregar. Na revisão das conversas de
2026-10-08 o pedido foi avisar ANTES.

Por isso o saldo é informado por variável — quanto havia e em que dia —, e
daqui para a frente a aplicação desconta o que ela mesma gastou (o custo de
cada resposta está em `AIReply`). O aviso sai quando o que resta passa do
limiar em dólares, ou quando, no ritmo dos últimos sete dias, acaba em
poucos dias. Ele aparece para a equipe (is_staff) na tela e no log em nível
de erro, uma vez por dia.
"""

import datetime
import logging
import os
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from ai_orchestrator.models import AIReply

logger = logging.getLogger(__name__)

VARIAVEL_CREDITO = "OPENAI_CREDITO_USD"
VARIAVEL_DATA = "OPENAI_CREDITO_EM"
VARIAVEL_LIMIAR = "OPENAI_AVISO_SALDO_USD"
LIMIAR_PADRAO = Decimal("20")
DIAS_DE_AVISO = 5
DIAS_DO_RITMO = 7


def _decimal(bruto: str) -> Decimal | None:
    try:
        valor = Decimal((bruto or "").strip().replace(",", "."))
    except (ArithmeticError, ValueError):
        return None
    return valor if valor >= 0 else None


def _gasto(desde: datetime.datetime) -> Decimal:
    total = AIReply.objects.filter(created_at__gte=desde).aggregate(total=Sum("cost_estimate"))["total"]
    return Decimal(total or 0)


def estimativa(agora: datetime.datetime | None = None) -> dict | None:
    """O saldo estimado, ou None quando o saldo não foi informado."""
    credito = _decimal(os.environ.get(VARIAVEL_CREDITO, ""))
    try:
        dia = datetime.date.fromisoformat(os.environ.get(VARIAVEL_DATA, "").strip())
    except ValueError:
        return None
    if credito is None:
        return None
    agora = agora or timezone.now()
    desde = timezone.make_aware(datetime.datetime.combine(dia, datetime.time.min))
    restante = credito - _gasto(desde)
    por_dia = _gasto(agora - datetime.timedelta(days=DIAS_DO_RITMO)) / DIAS_DO_RITMO
    dias = int(restante / por_dia) if por_dia > 0 and restante > 0 else None
    limiar = _decimal(os.environ.get(VARIAVEL_LIMIAR, "")) or LIMIAR_PADRAO
    return {
        "credito": credito,
        "desde": dia,
        "restante": restante,
        "por_dia": por_dia,
        "dias_restantes": dias,
        "alerta": restante <= limiar or (dias is not None and dias <= DIAS_DE_AVISO),
    }


def aviso(agora: datetime.datetime | None = None) -> str:
    """O texto do aviso para a equipe, ou "" quando o saldo está folgado."""
    situacao = estimativa(agora)
    if not situacao or not situacao["alerta"]:
        return ""
    restante = max(situacao["restante"], Decimal(0))
    texto = f"Saldo estimado da OpenAI: US$ {restante:.2f}"
    if situacao["restante"] <= 0:
        texto += " — o crédito informado já foi todo gasto"
    elif situacao["dias_restantes"] is not None:
        dias = situacao["dias_restantes"]
        quando = "menos de 1 dia" if dias < 1 else "1 dia" if dias == 1 else f"{dias} dias"
        texto += f" — no ritmo da última semana, acaba em {quando}"
    return texto + ". Recarregue a conta e atualize OPENAI_CREDITO_USD e OPENAI_CREDITO_EM."


def registrar_se_preciso(agora: datetime.datetime | None = None) -> None:
    """Grita no log uma vez por dia, quando o saldo está no fim. Nunca
    derruba a resposta: é aviso, não etapa."""
    try:
        texto = aviso(agora)
        if texto and cache.add(f"saldo_openai:avisado:{timezone.localdate()}", True, 60 * 60 * 24):
            logger.error(texto)
    except Exception:  # noqa: BLE001
        logger.warning("Não consegui estimar o saldo da OpenAI", exc_info=True)
