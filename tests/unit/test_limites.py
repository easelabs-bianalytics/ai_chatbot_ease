"""Cota diária de perguntas por pessoa.

O teto mensal (`budget.py`) protege a fatura do mês; este protege a de um
dia — alguém preso num laço, ou uma conta aberta e esquecida. Os dois valem
ao mesmo tempo, e este é conferido ANTES de qualquer chamada paga: quem
estourou não gasta nada para descobrir.

O que estes testes fixam:

1. os três perfis, e que a lista do time realmente não tem limite;
2. pergunta bloqueada não chama o modelo nem o banco;
3. esclarecimento, falha e interrupção NÃO descontam da cota — cobrar por
   elas seria cobrar a pessoa por um pedido nosso ou por um defeito nosso;
4. a cota é de cada pessoa, e é do dia de São Paulo.
"""

import datetime

import pytest
from django.utils import timezone

from ai_orchestrator import canned, limites
from ai_orchestrator.models import AIReply
from ai_orchestrator.orchestrator import handle_message
from catalog.loader import load_catalog
from conversations.models import Conversation
from datasource.executors.fake import FakeQueryExecutor, make_result
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta

pytestmark = pytest.mark.django_db

RESULTADO = make_result(("rede", "unidades"), [("Pague Menos", 47.0)])


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


def _pessoa(django_user_model, email):
    return django_user_model.objects.create_user(email, email=email, password="x")


def _conversa(user):
    return Conversation.objects.create(user=user)


def _perguntar(conversa, catalogo, texto="quantas unidades a Pague Menos vendeu em agosto de 2026?"):
    mensagem = Message.objects.create(
        conversation=conversa,
        direction=Message.Direction.INBOUND,
        content=texto,
        client_message_id=f"c-{timezone.now().timestamp()}",
        status=Message.Status.RECEIVED,
    )
    provider = ScriptedAIProvider([plano(sql="SELECT 1")], [resposta("47 unidades")])
    reply = handle_message(
        mensagem,
        channel=FakeChannel(),
        provider=provider,
        executor=FakeQueryExecutor([RESULTADO]),
        catalog=catalogo,
    )
    return reply, provider


def _gastar_cota(user, quantas, decision=AIReply.Decision.ANSWERED):
    """Respostas já dadas hoje, sem passar pelo orquestrador."""
    conversa = _conversa(user)
    for i in range(quantas):
        mensagem = Message.objects.create(
            conversation=conversa,
            direction=Message.Direction.INBOUND,
            content=f"pergunta {i}",
            client_message_id=f"gasto-{i}-{timezone.now().timestamp()}",
        )
        AIReply.objects.create(message=mensagem, decision=decision, reply_text="x")


# ------------------------------------------------------------- perfis


def test_time_do_produto_nao_tem_limite(django_user_model):
    for email in limites.SEM_LIMITE:
        assert limites.limite_de(_pessoa(django_user_model, email)) is None


def test_uso_frequente_tem_o_limite_folgado(django_user_model):
    for email in limites.COM_MAIS_CONSULTAS:
        pessoa = _pessoa(django_user_model, email)
        assert limites.limite_de(pessoa) == (12, 60)


def test_o_restante_do_dominio_tem_o_limite_menor(django_user_model):
    pessoa = _pessoa(django_user_model, "alguem.novo@easelabs.com.br")

    assert limites.limite_de(pessoa) == (7, 35)


def test_conta_antiga_sem_email_nao_fica_sem_limite(django_user_model):
    """Cadastro com só o `username` preenchido: cai no limite padrão, não no
    caminho de quem não tem limite."""
    pessoa = django_user_model.objects.create_user("ana", password="x")

    assert limites.limite_de(pessoa) == (limites.LIMITE_PADRAO, limites.SEMANAL_PADRAO)


# -------------------------------------------------------- o bloqueio


def test_quem_estourou_nao_chama_o_modelo(django_user_model, catalogo):
    pessoa = _pessoa(django_user_model, "alguem@easelabs.com.br")
    _gastar_cota(pessoa, limites.LIMITE_PADRAO)

    reply, provider = _perguntar(_conversa(pessoa), catalogo)

    assert reply.rule == "limite_diario_da_pessoa"
    assert reply.reply_text == canned.LIMITE_DIARIO
    # O número fica na auditoria, para quem administra; não no texto.
    assert reply.raw_response["limite"] == limites.LIMITE_PADRAO
    # O ponto da funcionalidade: nada foi gasto para dizer que não dá.
    assert provider.plan_requests == []
    assert provider.answer_requests == []


def test_uma_pergunta_antes_do_limite_ainda_passa(django_user_model, catalogo):
    pessoa = _pessoa(django_user_model, "alguem@easelabs.com.br")
    _gastar_cota(pessoa, limites.LIMITE_PADRAO - 1)

    reply, provider = _perguntar(_conversa(pessoa), catalogo)

    assert reply.decision == AIReply.Decision.ANSWERED
    assert provider.plan_requests != []


def test_quem_nao_tem_limite_passa_com_a_cota_estourada(django_user_model, catalogo):
    pessoa = _pessoa(django_user_model, "rubens.filho@easelabs.com.br")
    _gastar_cota(pessoa, 50)

    reply, _ = _perguntar(_conversa(pessoa), catalogo)

    assert reply.decision == AIReply.Decision.ANSWERED


# ------------------------------------------------- o que não desconta


@pytest.mark.parametrize("decisao", [
    AIReply.Decision.CLARIFY,
    AIReply.Decision.FAILED,
    AIReply.Decision.CANCELLED,
])
def test_pedido_de_detalhe_falha_e_interrupcao_nao_gastam_cota(django_user_model, catalogo, decisao):
    pessoa = _pessoa(django_user_model, "alguem@easelabs.com.br")
    _gastar_cota(pessoa, 30, decision=decisao)

    reply, _ = _perguntar(_conversa(pessoa), catalogo)

    assert reply.decision == AIReply.Decision.ANSWERED


# ------------------------------------------------------- de cada um


def test_a_cota_e_de_cada_pessoa(django_user_model, catalogo):
    ana = _pessoa(django_user_model, "ana@easelabs.com.br")
    bia = _pessoa(django_user_model, "bia@easelabs.com.br")
    _gastar_cota(ana, limites.LIMITE_PADRAO)

    reply, _ = _perguntar(_conversa(bia), catalogo)

    assert reply.decision == AIReply.Decision.ANSWERED


def test_resposta_de_ontem_nao_conta_no_dia_de_hoje(django_user_model):
    """Ontem sai da conta do dia; na semana, ela continua (se for a mesma)."""
    pessoa = _pessoa(django_user_model, "alguem@easelabs.com.br")
    _gastar_cota(pessoa, limites.LIMITE_PADRAO)
    ontem = timezone.now() - datetime.timedelta(days=1)
    AIReply.objects.update(created_at=ontem)

    assert limites.usadas_hoje(pessoa) == 0
    assert limites.excedeu(pessoa) is False


def test_a_semana_segura_quem_faz_o_maximo_todo_dia(django_user_model, catalogo):
    """Sem o teto semanal, sete por dia durante sete dias viram 49 e o
    limite diário nunca encostaria em ninguém."""
    pessoa = _pessoa(django_user_model, "alguem@easelabs.com.br")
    _gastar_cota(pessoa, limites.SEMANAL_PADRAO)
    # tudo de ontem: o dia está zerado, a semana não
    AIReply.objects.update(created_at=timezone.now() - datetime.timedelta(days=1))
    if timezone.localdate().weekday() == 0:
        pytest.skip("segunda-feira: ontem é da semana passada")

    cota = limites.situacao(pessoa)
    assert cota["dia"]["usadas"] == 0
    assert cota["semana"]["excedeu"] is True
    assert cota["motivo"] == "semana"

    reply, provider = _perguntar(_conversa(pessoa), catalogo)

    assert reply.rule == "limite_diario_da_pessoa"
    assert "semana" in reply.reply_text
    assert provider.plan_requests == []


def test_situacao_mostra_quanto_falta(django_user_model):
    pessoa = _pessoa(django_user_model, "alguem@easelabs.com.br")
    _gastar_cota(pessoa, 3)

    assert limites.situacao(pessoa) == {
        "dia": {"limite": 7, "usadas": 3, "restante": 4, "excedeu": False},
        "semana": {"limite": 35, "usadas": 3, "restante": 32, "excedeu": False},
        "excedeu": False,
        "motivo": "",
    }


def test_sem_limite_nao_gasta_consulta_para_contar(django_user_model, django_assert_num_queries):
    """Quem não tem limite não precisa de uma contagem no banco a cada
    pergunta — e são justamente as pessoas que mais perguntam."""
    pessoa = _pessoa(django_user_model, "gustavo@easelabs.com.br")

    with django_assert_num_queries(0):
        limites.situacao(pessoa)


def test_mensagem_de_cota_diz_quando_volta_e_nao_diz_quantas():
    """Diz quando volta, que é o que a pessoa pode fazer a respeito; não diz
    o número, porque a aba de limites também não diz — duas telas do mesmo
    produto não podem discordar sobre o que a pessoa pode saber.

    E cada janela diz o SEU prazo: "volta amanhã" numa cota semanal seria
    mentira."""
    assert "amanhã" in canned.LIMITE_DIARIO
    assert "segunda" in canned.LIMITE_SEMANAL
    # O único número é o 100%, que é a fração — não a contagem.
    for texto in (canned.LIMITE_DIARIO, canned.LIMITE_SEMANAL):
        assert [p for p in texto.split() if any(c.isdigit() for c in p)] == ["100%"]
