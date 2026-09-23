"""A apresentação do Jarvis no primeiro login.

A regra é **uma vez por pessoa**, não por navegador: quem já conheceu o
Jarvis e entra de outro computador não vê a apresentação de novo, e quem
limpou o navegador também não. Por isso a marca é uma linha no banco e não
uma chave no `localStorage` — o que o navegador guarda (em que quadro parou,
quantos convites recebeu) é conforto local e pode sumir sem prejuízo.

O que estes testes fixam:

1. quem nunca entrou recebe `passeio_pendente` na sessão;
2. depois de marcado, não recebe mais — em nenhum navegador;
3. marcar duas vezes não quebra (a tela pode chamar de novo);
4. a marca de uma pessoa não vale para outra.
"""

import pytest
from rest_framework.test import APIClient

from web.models import PrimeiroAcesso

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(django_user_model):
    return django_user_model.objects.create_user("ana", email="ana@easelabs.com.br", password="x")


@pytest.fixture
def cliente(ana):
    cliente = APIClient()
    cliente.force_authenticate(ana)
    return cliente


def _sessao(cliente):
    return cliente.get("/api/auth/sessao/").json()


def test_quem_nunca_entrou_ve_a_apresentacao(cliente):
    assert _sessao(cliente)["usuario"]["passeio_pendente"] is True


def test_depois_de_visto_nao_aparece_mais(cliente):
    assert cliente.post("/api/auth/passeio/", {}, format="json").status_code == 200

    assert _sessao(cliente)["usuario"]["passeio_pendente"] is False


def test_outro_navegador_da_mesma_pessoa_tambem_nao_ve(cliente, ana):
    """O ponto de a marca ser do usuário: o `localStorage` do outro
    computador está vazio, e ainda assim ela não vê de novo."""
    cliente.post("/api/auth/passeio/", {}, format="json")

    outro = APIClient()
    outro.force_authenticate(ana)

    assert _sessao(outro)["usuario"]["passeio_pendente"] is False


def test_marcar_duas_vezes_nao_quebra(cliente):
    cliente.post("/api/auth/passeio/", {}, format="json")

    assert cliente.post("/api/auth/passeio/", {}, format="json").status_code == 200
    assert PrimeiroAcesso.objects.count() == 1


def test_a_marca_e_de_cada_pessoa(cliente, django_user_model):
    cliente.post("/api/auth/passeio/", {}, format="json")

    bia = django_user_model.objects.create_user("bia", password="x")
    dela = APIClient()
    dela.force_authenticate(bia)

    assert _sessao(dela)["usuario"]["passeio_pendente"] is True


def test_visitante_nao_marca_nada():
    """Sem sessão não há de quem guardar a marca."""
    anonimo = APIClient()

    resposta = anonimo.post("/api/auth/passeio/", {}, format="json")

    assert resposta.status_code in (401, 403)
    assert PrimeiroAcesso.objects.count() == 0
