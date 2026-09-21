"""Prévia da imagem na conversa (ADR-0024).

O print some depois da resposta; a miniatura é o que fica para a conversa
mostrar, como nas outras IAs. Pequena, só da dona da conversa, e nunca
impede a pergunta de sair.
"""

import io

import pytest
from PIL import Image
from rest_framework.test import APIClient

from attachments.imagem import LADO_DA_MINIATURA
from messaging.models import Message
from tests.integration.test_anexos_api import _png, _subir, _xlsx, ana, cliente, conversa  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def sem_worker(monkeypatch):
    monkeypatch.setattr("messaging.views.process_message.delay", lambda *a, **k: None)


def _perguntar(cliente, conversa, etiqueta, texto="o que mostra?"):
    return cliente.post(
        f"/api/conversations/{conversa.pk}/messages/",
        {"client_message_id": "c-1", "text": texto, "anexo": etiqueta},
        format="json",
    )


def test_pergunta_com_imagem_guarda_miniatura_pequena(cliente, conversa):
    etiqueta = _subir(cliente, conversa, "print.png", _png(1920, 1080)).json()

    _perguntar(cliente, conversa, etiqueta)

    mensagem = Message.objects.get()
    miniatura = Image.open(io.BytesIO(bytes(mensagem.anexo_miniatura)))
    assert miniatura.format == "JPEG"
    assert max(miniatura.size) == LADO_DA_MINIATURA
    # Fica no banco para sempre: tem de ser pequena.
    assert len(mensagem.anexo_miniatura) < 60_000


def test_conversa_aponta_a_miniatura_e_ela_e_servida(cliente, conversa):
    etiqueta = _subir(cliente, conversa, "print.png", _png(800, 400)).json()
    _perguntar(cliente, conversa, etiqueta)

    anexo = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"][0]["anexo"]
    r = cliente.get(anexo["miniatura"])

    assert r.status_code == 200
    assert r["Content-Type"] == "image/jpeg"
    assert "immutable" in r["Cache-Control"]


def test_miniatura_de_outra_pessoa_nao_e_servida(cliente, conversa, django_user_model):
    etiqueta = _subir(cliente, conversa, "print.png", _png(800, 400)).json()
    _perguntar(cliente, conversa, etiqueta)
    mensagem = Message.objects.get()
    bia = APIClient()
    bia.force_authenticate(django_user_model.objects.create_user("bia", password="x"))

    r = bia.get(f"/api/conversations/{conversa.pk}/messages/{mensagem.pk}/miniatura/")

    assert r.status_code == 404


def test_planilha_nao_tem_miniatura(cliente, conversa):
    etiqueta = _subir(cliente, conversa, "redes.xlsx", _xlsx()).json()
    _perguntar(cliente, conversa, etiqueta, "preencha")

    anexo = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"][0]["anexo"]

    assert "miniatura" not in anexo


def test_imagem_vencida_nao_impede_a_pergunta(cliente, conversa):
    """Sem os bytes não há prévia — mas a pergunta sai, e o worker explica."""
    etiqueta = {"token": "vencido", "tipo": "imagem", "nome": "print.png", "resumo": "Imagem"}

    r = _perguntar(cliente, conversa, etiqueta)

    assert r.status_code == 202
    assert Message.objects.get().anexo_miniatura is None
