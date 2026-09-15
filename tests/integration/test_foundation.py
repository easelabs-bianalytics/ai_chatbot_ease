"""Fundação: healthcheck, autenticação padrão, Admin e migrations."""

import pytest
from django.core.management import call_command
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView


def test_health_responde_sem_login_e_sem_banco():
    """Healthcheck do Railway. Este teste não tem o marcador django_db: se a
    view tocasse o banco, o pytest-django falharia. É de propósito — com o
    Postgres fora, a plataforma não deve matar e recriar o container em laço."""
    response = APIClient().get("/api/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class _ViewSemPermissaoDeclarada(APIView):
    def get(self, request):
        return Response({"dado": "de negócio"})


def test_api_exige_login_por_padrao():
    """ADR-0011. Na referência o projeto não definia REST_FRAMEWORK e o DRF
    aplicou AllowAny: os webhooks ficaram abertos até o deploy revelar a
    falha. Aqui uma view nova que não declara permissão nasce fechada."""
    request = APIRequestFactory().get("/qualquer/")

    response = _ViewSemPermissaoDeclarada.as_view()(request)

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_exige_login(client):
    response = client.get("/admin/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_superusuario_entra_no_admin(admin_client):
    """Prova de ponta a ponta que o banco de testes sobe, as migrations
    aplicam e o Admin — o painel de auditoria do MVP (ADR-0001) — renderiza."""
    assert admin_client.get("/admin/").status_code == 200


@pytest.mark.django_db
def test_nenhuma_migration_pendente():
    """Model alterado sem migration só aparece no deploy, quando o `migrate`
    do start do container não cria a coluna e a aplicação quebra em produção."""
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)
