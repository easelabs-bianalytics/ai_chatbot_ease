"""Relatório de uso (Fase 8, FR-16).

O relatório é lido para decidir coisas — se o custo está no rumo, se o tempo
de resposta piorou, o que falta no catálogo. Número errado aqui leva a
decisão errada, então o que se fixa nos testes é a aritmética: o que entra na
janela, o que fica de fora e como cada indicador é contado.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from ai_orchestrator.models import AICall, AIReply, CatalogGap
from conversations.models import Conversation
from datasource.models import QueryRun
from messaging.models import Message
from reporting.services import montar_relatorio

pytestmark = pytest.mark.django_db


def _pergunta(usuario, quando, decisao=AIReply.Decision.ANSWERED, custo="0.04",
              latencia=10000, regra="", conversa=None):
    """Uma pergunta respondida, com a auditoria que ela geraria de verdade."""
    conversa = conversa or Conversation.objects.create(user=usuario)
    mensagem = Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND,
        content="quantas unidades em agosto?", client_message_id=f"c-{timezone.now().timestamp()}-{id(quando)}",
    )
    reply = AIReply.objects.create(
        message=mensagem, decision=decisao, rule=regra,
        tokens_input=1000, tokens_output=100,
        cost_estimate=Decimal(custo), latency_ms=latencia,
    )
    # created_at é auto_now_add: só dá para posicionar no tempo depois.
    AIReply.objects.filter(pk=reply.pk).update(created_at=quando)
    Message.objects.filter(pk=mensagem.pk).update(created_at=quando)
    reply.refresh_from_db()
    return reply


@pytest.fixture
def ana(django_user_model):
    return django_user_model.objects.create_user("ana", password="x")


def test_conta_perguntas_pessoas_e_conversas(ana, django_user_model):
    agora = timezone.now()
    bruno = django_user_model.objects.create_user("bruno", password="x")
    conversa = Conversation.objects.create(user=ana)
    _pergunta(ana, agora - timedelta(hours=1), conversa=conversa)
    _pergunta(ana, agora - timedelta(hours=2), conversa=conversa)
    _pergunta(bruno, agora - timedelta(hours=3))

    r = montar_relatorio(dias=30)

    assert r.perguntas == 3
    assert r.pessoas == 2
    assert r.conversas == 2


def test_ignora_o_que_esta_fora_da_janela(ana):
    agora = timezone.now()
    _pergunta(ana, agora - timedelta(days=2))
    _pergunta(ana, agora - timedelta(days=40))

    r = montar_relatorio(dias=7)

    assert r.perguntas == 1


def test_taxa_e_decisoes_saem_da_auditoria(ana):
    agora = timezone.now()
    for _ in range(3):
        _pergunta(ana, agora - timedelta(minutes=10))
    _pergunta(ana, agora - timedelta(minutes=20), decisao=AIReply.Decision.CLARIFY)

    r = montar_relatorio(dias=7)

    assert r.decisoes[AIReply.Decision.ANSWERED] == 3
    assert r.decisoes[AIReply.Decision.CLARIFY] == 1
    assert r.com_dado == 3
    assert r.taxa_com_dado == pytest.approx(0.75)


def test_custo_soma_e_projeta_o_mes(ana):
    agora = timezone.now()
    _pergunta(ana, agora - timedelta(days=1), custo="0.05")
    _pergunta(ana, agora - timedelta(days=2), custo="0.03")

    r = montar_relatorio(dias=10)

    assert r.custo == Decimal("0.08")
    assert r.custo_por_pergunta == Decimal("0.0400")
    # 0,08 em 10 dias vira 0,24 em 30
    assert r.custo_projetado_mes == Decimal("0.24")


def test_latencia_so_conta_pergunta_que_foi_ao_banco(ana):
    """Conversa e recusa respondem em dois segundos e puxariam o p95 para
    baixo, escondendo que a consulta está demorando."""
    agora = timezone.now()
    for ms in (5000, 9000, 30000):
        _pergunta(ana, agora - timedelta(minutes=5), latencia=ms)
    _pergunta(ana, agora - timedelta(minutes=6), decisao=AIReply.Decision.CONVERSATION, latencia=800)

    r = montar_relatorio(dias=7)

    assert r.latencias == (5000, 9000, 30000)
    assert r.percentil(0.5) == 9000
    assert r.percentil(1.0) == 30000


def test_consultas_corrigidas_erros_e_reescritas(ana):
    agora = timezone.now()
    reply = _pergunta(ana, agora - timedelta(minutes=5))
    QueryRun.objects.create(ai_reply=reply, attempt=1, sql="SELECT 1",
                            guard_result=QueryRun.GuardResult.APPROVED,
                            status=QueryRun.Status.ERROR)
    QueryRun.objects.create(ai_reply=reply, attempt=2, sql="SELECT 2",
                            guard_result=QueryRun.GuardResult.APPROVED,
                            status=QueryRun.Status.SUCCESS)
    AICall.objects.create(ai_reply=reply, stage=AICall.Stage.ANSWER, model="x")
    AICall.objects.create(ai_reply=reply, stage=AICall.Stage.REWRITE, model="x")

    r = montar_relatorio(dias=7)

    assert r.consultas == 2
    assert r.consultas_corrigidas == 1
    assert r.consultas_com_erro == 1
    assert r.reescritas == 1


def test_lacunas_abertas_aparecem_com_pergunta_e_motivo(ana):
    agora = timezone.now()
    reply = _pergunta(ana, agora - timedelta(minutes=5), decisao=AIReply.Decision.UNKNOWN)
    lacuna = CatalogGap.objects.create(
        message=reply.message, question="qual a margem por SKU?", reason="não existe no catálogo",
    )
    CatalogGap.objects.filter(pk=lacuna.pk).update(created_at=agora - timedelta(minutes=5))
    resolvida = CatalogGap.objects.create(message=reply.message, question="outra", status=CatalogGap.Status.RESOLVED)
    CatalogGap.objects.filter(pk=resolvida.pk).update(created_at=agora - timedelta(minutes=5))

    r = montar_relatorio(dias=7)

    assert r.lacunas_abertas == 1
    assert r.lacunas[0].pergunta == "qual a margem por SKU?"
    assert "catálogo" in r.lacunas[0].motivo


def test_serie_diaria_agrupa_no_fuso_local(ana):
    """Agrupar por dia em UTC jogaria toda pergunta feita depois das 21h
    para o dia seguinte."""
    fim = timezone.localtime().replace(hour=23, minute=30, second=0, microsecond=0)
    _pergunta(ana, fim - timedelta(hours=1))   # mesmo dia local, já é outro em UTC
    _pergunta(ana, fim - timedelta(days=1))

    r = montar_relatorio(inicio=fim - timedelta(days=3), fim=fim + timedelta(minutes=1))

    assert len(r.por_dia) == 2
    assert r.por_dia[-1].data == timezone.localtime(fim).strftime("%d/%m/%Y")
    assert r.por_dia[-1].perguntas == 1


def test_periodo_sem_pergunta_nao_divide_por_zero(ana):
    r = montar_relatorio(dias=7)

    assert r.perguntas == 0
    assert r.taxa_com_dado == 0.0
    assert r.custo_por_pergunta == Decimal("0")
    assert r.percentil(0.95) == 0


# --- comando -----------------------------------------------------------------


def test_comando_mostra_o_resumo(ana, capsys):
    _pergunta(ana, timezone.now() - timedelta(hours=1))

    call_command("bi_report", dias=7)

    saida = capsys.readouterr().out
    assert "Perguntas" in saida and "Custo" in saida
    assert "Saiu com número" in saida


def test_comando_avisa_quando_nao_houve_pergunta(ana, capsys):
    call_command("bi_report", dias=7)

    assert "Nenhuma pergunta" in capsys.readouterr().out


def test_comando_grava_csv_com_uma_linha_por_dia(ana, tmp_path, capsys):
    _pergunta(ana, timezone.now() - timedelta(hours=1), custo="0.02")
    destino = tmp_path / "uso.csv"

    call_command("bi_report", dias=7, csv=str(destino))

    linhas = destino.read_text(encoding="utf-8-sig").strip().splitlines()
    assert linhas[0] == "dia;perguntas;com_numero;custo_usd"
    assert linhas[1].endswith(";1;1;0.020000")


def test_comando_recusa_data_mal_escrita(ana):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="AAAA-MM-DD"):
        call_command("bi_report", desde="01/09/2026")
