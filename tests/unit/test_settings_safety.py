"""A suíte de testes nunca enxerga credenciais nem serviços reais."""

import os

import openai
import pytest
from django.conf import settings

from tests.conftest import REAL_SERVICE_ENV_VARS, RealAIClientBlocked


def test_suite_roda_com_settings_de_teste_sem_carregar_o_env():
    """O bi/.env tem credenciais reais da AWS. Se a suíte o carregasse, um
    teste poderia usá-las por acidente — e qualquer variável de banco lá
    dentro poderia virar o servidor onde o pytest-django cria e apaga bancos."""
    # settings.SETTINGS_MODULE não serve aqui: a fixture `settings` do
    # pytest-django (usada no conftest) troca o objeto durante o teste.
    assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings_test"
    assert settings.SECRET_KEY == "chave-usada-somente-nos-testes"
    assert os.environ.get("BI_SKIP_DOTENV") == "1"


def test_banco_dos_testes_e_o_postgres_local():
    """O pytest-django cria e destrói um banco `test_*` no servidor
    configurado. Ele tem de ser o Postgres local, salvo override explícito."""
    if os.environ.get("TEST_APP_DATABASE_URL"):
        pytest.skip("servidor de testes definido explicitamente")
    assert settings.DATABASES["default"]["HOST"] in {"localhost", "127.0.0.1"}


def test_credenciais_de_servicos_reais_nao_chegam_aos_testes():
    for name in REAL_SERVICE_ENV_VARS:
        assert name not in os.environ


def test_cliente_real_da_openai_e_bloqueado():
    """Teste que esquecesse de mockar o client gastaria tokens e dependeria de
    rede. Ele falha na criação do client, antes de qualquer chamada."""
    with pytest.raises(RealAIClientBlocked):
        openai.OpenAI(api_key="sk-teste")


def test_celery_reentrega_tarefa_se_o_worker_cair():
    """Na referência, o Celery confirmava a tarefa antes de executá-la: um
    worker que caía no meio deixava a mensagem presa, sem resposta e sem
    aviso. Com acks_late a tarefa volta para a fila."""
    from config.celery import app

    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
