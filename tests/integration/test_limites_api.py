"""A aba de limites de uso.

Ela existe para a cota não ser uma surpresa: descobrir o limite no instante
em que ele bate é a pior hora de saber que ele existe.

O que estes testes fixam:

1. a aba manda porcentagem, nunca a contagem — e ela acompanha o perfil;
   quem não tem limite recebe `null` (a tela diz "sem limite" em vez de
   desenhar uma barra vazia);
2. a aba não fala de dinheiro, para ninguém — é contagem de perguntas;
3. visitante não lê cota de ninguém.
"""

import pytest
from rest_framework.test import APIClient

from ai_orchestrator.models import AIReply
from conversations.models import Conversation
from messaging.models import Message

pytestmark = pytest.mark.django_db


def _cliente(user):
    cliente = APIClient()
    cliente.force_authenticate(user)
    return cliente


def _gastar(user, quantas):
    conversa = Conversation.objects.create(user=user)
    for i in range(quantas):
        mensagem = Message.objects.create(
            conversation=conversa,
            direction=Message.Direction.INBOUND,
            content=f"pergunta {i}",
            client_message_id=f"c-{i}",
        )
        AIReply.objects.create(message=mensagem, decision=AIReply.Decision.ANSWERED, reply_text="x")


def test_a_aba_manda_porcentagem_e_nao_a_contagem(django_user_model):
    """3 de 7 é 43%. O número absoluto não sai daqui: esconder só na tela
    seria esconder da vista, não do usuário — a resposta inteira aparece no
    navegador de quem procurar."""
    ana = django_user_model.objects.create_user(
        "ana@easelabs.com.br", email="ana@easelabs.com.br", password="x"
    )
    _gastar(ana, 3)

    dados = _cliente(ana).get("/api/auth/limites/").json()

    assert dados["dia"] == {"pct": 43, "excedeu": False}
    assert dados["semana"] == {"pct": 9, "excedeu": False}
    assert dados["excedeu"] is False
    # a tela mostra quando cada janela volta
    assert dados["renova_em"] and dados["semana_renova_em"]
    assert "7" not in str(dados["dia"]) and "usadas" not in str(dados)


def test_a_porcentagem_acompanha_o_perfil(django_user_model):
    """Três perguntas são 43% de quem tem 7 e 25% de quem tem 12."""
    renato = django_user_model.objects.create_user(
        "renato_avilla@easelabs.com.br", email="renato_avilla@easelabs.com.br", password="x"
    )
    _gastar(renato, 3)

    dados = _cliente(renato).get("/api/auth/limites/").json()

    assert dados["dia"]["pct"] == 25
    assert dados["semana"]["pct"] == 5


def test_quem_nao_tem_limite_recebe_nulo(django_user_model):
    rubens = django_user_model.objects.create_user(
        "rubens.filho@easelabs.com.br", email="rubens.filho@easelabs.com.br", password="x"
    )

    dados = _cliente(rubens).get("/api/auth/limites/").json()

    assert dados["dia"] is None
    assert dados["semana"] is None
    assert dados["excedeu"] is False


def test_a_aba_nao_fala_de_dinheiro(django_user_model):
    """Quem pergunta precisa saber quanto ainda pode perguntar. Custo é
    problema de quem administra, e mora no relatório — não na tela de quem
    só quer fazer a próxima pergunta."""
    chefe = django_user_model.objects.create_user("chefe", password="x", is_staff=True)

    dados = _cliente(chefe).get("/api/auth/limites/").json()

    assert "mes" not in dados
    assert not any("custo" in c or "gasto" in c or "usd" in c for c in map(str.lower, dados))


def test_visitante_nao_le_cota():
    assert APIClient().get("/api/auth/limites/").status_code in (401, 403)
