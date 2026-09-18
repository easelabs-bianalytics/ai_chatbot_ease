import openai
import pytest

# Variáveis que dão acesso a serviço real (e custam dinheiro ou tocam o banco
# de negócio). O settings de teste já não carrega o bi/.env, mas elas ainda
# podem vir do shell de quem roda a suíte.
REAL_SERVICE_ENV_VARS = (
    "AI_PROVIDER",
    "AI_PROVIDER_API_KEY",
    "ANALYTICS_DATABASE_URL",
    "ANALYTICS_DB_HOST",
    "ANALYTICS_DB_PORT",
    "ANALYTICS_DB_NAME",
    "ANALYTICS_DB_USER",
    "ANALYTICS_DB_PASS",
)


class RealAIClientBlocked(RuntimeError):
    """Um teste tentou criar um cliente real da OpenAI."""


@pytest.fixture(autouse=True)
def sem_credenciais_de_servicos_reais(monkeypatch):
    """Nenhum teste enxerga credencial real, venha ela de onde vier."""
    for name in REAL_SERVICE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def bloqueia_cliente_openai_real(monkeypatch):
    """Teste que esquecesse de injetar um client mockado gastaria tokens e
    dependeria de rede. Aqui ele falha alto, na hora."""

    def _recusa(*args, **kwargs):
        raise RealAIClientBlocked(
            "Teste tentou criar um cliente real da OpenAI. Use um provider "
            "fake (tests/fakes/) ou injete um client mockado."
        )

    monkeypatch.setattr(openai.OpenAI, "__init__", _recusa)
    monkeypatch.setattr(openai.AsyncOpenAI, "__init__", _recusa)


@pytest.fixture(autouse=True)
def celery_tasks_run_eagerly(settings):
    """Tarefas Celery rodam síncronas, no mesmo processo e transação do teste
    (ADR-0003), sem depender de Redis nem de worker."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
