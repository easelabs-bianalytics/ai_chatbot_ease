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


def test_health_responde_ao_alb_pelo_ip_privado_da_task():
    """O ALB testa a saúde batendo no IP privado da task, e o Host chega como
    `10.0.1.23:8000` — fora do ALLOWED_HOSTS, que é feito de domínios. Sem o
    HealthCheckMiddleware na frente, o Django responde 400 e o alvo fica
    "unhealthy" para sempre, com a aplicação perfeita."""
    response = APIClient().get("/api/health/", HTTP_HOST="10.0.1.23:8000")

    assert response.status_code == 200


def test_ip_privado_continua_recusado_fora_do_health_check():
    """O atalho vale só para o caminho de saúde: o resto da aplicação segue
    exigindo um host conhecido."""
    response = APIClient().get("/", HTTP_HOST="10.0.1.23:8000")

    assert response.status_code == 400


def test_estaticos_passam_pelo_manifest_como_no_build_da_imagem(tmp_path, settings):
    """A suíte usa o armazenamento simples de estáticos; o build da imagem usa
    o com manifest, que segue as referências de dentro dos arquivos. Em
    2026-09-21 o build quebrou: o Chart.js vendorizado apontava para um
    `chart.umd.js.map` que nunca foi incluído. Aqui roda do jeito do build."""
    settings.STATIC_ROOT = tmp_path
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

    call_command("collectstatic", "--noinput", verbosity=0)

    assert (tmp_path / "staticfiles.json").exists()


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
