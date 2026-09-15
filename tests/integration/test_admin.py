"""O Admin é o painel de auditoria do MVP (ADR-0001, PM-11)."""

import pytest
from django.contrib import admin
from django.urls import reverse

MODELOS_REGISTRADOS = [
    (model._meta.app_label, model._meta.model_name) for model in admin.site._registry
]


@pytest.mark.django_db
@pytest.mark.parametrize("app_label, model_name", MODELOS_REGISTRADOS)
def test_listagem_do_admin_abre(admin_client, app_label, model_name):
    """Erro em list_display, list_filter ou inline só aparece quando alguém
    abre a tela — e quem abre é a equipe de BI, atrás de uma resposta
    específica, no pior momento para descobrir isso."""
    url = reverse(f"admin:{app_label}_{model_name}_changelist")

    assert admin_client.get(url).status_code == 200
