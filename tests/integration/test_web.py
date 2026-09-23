"""Interface web: página, login por sessão e a fonte de cada resposta (Fase 6).

O login é a porta do dado de negócio; a fonte é o que faz o usuário
confiar num número sem confiar na IA. Os dois têm teste aqui.
"""

import json

import pytest
from django.test import Client
from rest_framework.test import APIClient

from ai_orchestrator.models import AIReply
from ai_orchestrator.orchestrator import handle_message
from catalog.loader import load_catalog
from conversations.models import Conversation
from datasource.executors.fake import FakeQueryExecutor, make_result
from datasource.models import QueryRun
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(django_user_model):
    return django_user_model.objects.create_user(
        "ana", password="senha-forte-123", first_name="Ana", last_name="Souza"
    )


@pytest.fixture
def senha_ligada(settings):
    """Usuário e senha só existem com LOGIN_POR_SENHA=1 (desenvolvimento).
    Os testes desta seção provam que, ligado, ele continua seguro."""
    settings.LOGIN_POR_SENHA = True


def _csrf(cliente) -> str:
    cliente.get("/api/auth/sessao/")
    return cliente.cookies["csrftoken"].value


def _login(cliente, usuario="ana", senha="senha-forte-123"):
    token = _csrf(cliente)
    return cliente.post(
        "/api/auth/login/",
        data=json.dumps({"usuario": usuario, "senha": senha}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )


# --- página ---------------------------------------------------------------


def test_pagina_do_chat_entrega_o_app_e_o_cookie_de_csrf():
    """Sem o cookie, o primeiro POST da página (o login) seria recusado."""
    resposta_http = Client().get("/")

    assert resposta_http.status_code == 200
    assert b"web/app.js" in resposta_http.content
    assert "csrftoken" in resposta_http.cookies


def test_rota_de_conversa_tambem_entrega_a_pagina():
    """Um F5 em /conversas/12 não pode cair num 404."""
    assert Client().get("/conversas/12").status_code == 200


# --- login ----------------------------------------------------------------


def test_sessao_anonima_diz_que_nao_ha_ninguem():
    assert Client().get("/api/auth/sessao/").json() == {"autenticado": False}


def test_login_por_senha_vem_desligado(ana):
    """Com ele ligado, a conta `demo` e qualquer senha antiga seriam porta de
    entrada sem e-mail da empresa (decisão de 2026-09-21)."""
    resposta_http = _login(Client(enforce_csrf_checks=True))

    assert resposta_http.status_code == 403
    assert "@easelabs.com.br" in resposta_http.json()["error"]
    assert Client().get("/api/auth/sessao/").json()["autenticado"] is False


def test_login_sem_csrf_e_recusado(ana, senha_ligada):
    """Sem a checagem, outro site conseguiria logar a vítima na conta do
    atacante — e as perguntas dela iriam para o histórico dele."""
    cliente = Client(enforce_csrf_checks=True)

    resposta_http = cliente.post(
        "/api/auth/login/",
        data=json.dumps({"usuario": "ana", "senha": "senha-forte-123"}),
        content_type="application/json",
    )

    assert resposta_http.status_code == 403


def test_login_certo_abre_a_sessao(ana, senha_ligada):
    cliente = Client(enforce_csrf_checks=True)

    resposta_http = _login(cliente)

    assert resposta_http.status_code == 200
    assert resposta_http.json()["usuario"] == {
        "usuario": "ana", "email": "", "nome": "Ana Souza", "iniciais": "AS", "equipe": False,
        # Primeiro login: a tela abre a apresentação do Jarvis antes da conversa.
        "passeio_pendente": True,
    }
    assert cliente.get("/api/auth/sessao/").json()["autenticado"] is True


@pytest.mark.parametrize("usuario,senha", [("ana", "errada"), ("ninguem", "senha-forte-123")])
def test_login_errado_nao_diz_o_que_errou(ana, senha_ligada, usuario, senha):
    """Dizer se o usuário existe ajudaria quem tenta adivinhar contas."""
    resposta_http = _login(Client(enforce_csrf_checks=True), usuario, senha)

    assert resposta_http.status_code == 400
    assert resposta_http.json()["error"] == "Usuário ou senha incorretos."


def test_usuario_desativado_nao_entra(ana, senha_ligada):
    ana.is_active = False
    ana.save()

    assert _login(Client(enforce_csrf_checks=True)).status_code == 400


def test_logout_encerra_a_sessao(ana, senha_ligada):
    cliente = Client(enforce_csrf_checks=True)
    _login(cliente)
    token = cliente.cookies["csrftoken"].value

    saida = cliente.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=token)

    assert saida.status_code == 204
    assert cliente.get("/api/conversations/").status_code == 403


# --- fonte da resposta ----------------------------------------------------


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


def _responder(usuario, catalogo, texto="unidades da Pague Menos em 2026"):
    conversa = Conversation.objects.create(user=usuario)
    pergunta = Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND,
        content=texto, client_message_id="c-1",
    )
    handle_message(
        pergunta,
        channel=FakeChannel(),
        provider=ScriptedAIProvider(
            [plano(sql="SELECT und FROM cddd.vendas_consolidado", reference_query_id="B11")],
            [resposta("Foram 47 unidades.")],
        ),
        executor=FakeQueryExecutor([make_result(("unidades",), [(47,)])]),
        catalog=catalogo,
    )
    return conversa, pergunta


def test_resposta_fica_ligada_a_pergunta(ana, catalogo):
    """É o vínculo que leva a fonte até a resposta na tela."""
    conversa, pergunta = _responder(ana, catalogo)

    saida = conversa.messages.get(direction=Message.Direction.OUTBOUND)

    assert saida.in_reply_to_id == pergunta.pk


def test_resposta_traz_a_consulta_a_referencia_e_o_momento(ana, catalogo):
    conversa, pergunta = _responder(ana, catalogo)
    cliente = APIClient()
    cliente.force_login(ana)

    mensagens = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"]
    saida = mensagens[-1]

    assert saida["direction"] == "out"
    assert saida["in_reply_to"] == pergunta.pk
    fonte = saida["fonte"]
    assert fonte["decisao"] == "answered"
    assert fonte["consulta"]["sql"] == "SELECT und FROM cddd.vendas_consolidado"
    assert fonte["consulta"]["referencia"] == "B11"
    assert fonte["consulta"]["linhas"] == 1
    assert fonte["respondida_em"]


def test_custo_so_aparece_para_a_equipe(ana, catalogo, django_user_model):
    """Custo e tokens interessam a quem administra; para o resto, é ruído."""
    conversa, _ = _responder(ana, catalogo)
    cliente = APIClient()
    cliente.force_login(ana)

    fonte = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"][-1]["fonte"]
    assert "custo_usd" not in fonte

    ana.is_staff = True
    ana.save()
    fonte = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"][-1]["fonte"]
    assert fonte["custo_usd"] == pytest.approx(0.003)
    assert fonte["tokens"] == 340


def test_resposta_sem_consulta_nao_inventa_fonte(ana, catalogo):
    """Esclarecimento não rodou consulta nenhuma: mostrar "0 linhas" daria a
    impressão de que o banco foi consultado."""
    conversa = Conversation.objects.create(user=ana)
    pergunta = Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND,
        content="quanto vendemos?", client_message_id="c-2",
    )
    from ai_orchestrator.providers.base import Plan

    handle_message(
        pergunta,
        channel=FakeChannel(),
        provider=ScriptedAIProvider(
            [plano(intent=Plan.Intent.CLARIFY, sql="", clarification_question="De qual período?")]
        ),
        executor=FakeQueryExecutor(),
        catalog=catalogo,
    )
    cliente = APIClient()
    cliente.force_login(ana)

    fonte = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"][-1]["fonte"]

    assert fonte["decisao"] == AIReply.Decision.CLARIFY
    assert fonte["consulta"] is None
    assert QueryRun.objects.count() == 0


def test_pergunta_nao_carrega_fonte(ana, catalogo):
    conversa, _ = _responder(ana, catalogo)
    cliente = APIClient()
    cliente.force_login(ana)

    entrada = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"][0]

    assert entrada["direction"] == "in"
    assert "fonte" not in entrada
