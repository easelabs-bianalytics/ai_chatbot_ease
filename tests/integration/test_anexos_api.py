"""API de anexos (ADR-0024): subida, recusa e download da planilha preenchida.

A subida é onde a maior parte do custo é evitada: arquivo grande, formato
errado ou imagem falsa são recusados aqui, antes de qualquer chamada de
modelo. E a conversa de outra pessoa continua invisível.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from PIL import Image
from rest_framework.test import APIClient

from attachments import deposito
from attachments.limites import MAX_BYTES
from conversations.models import Conversation
from messaging.models import Message

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(django_user_model):
    return django_user_model.objects.create_user("ana", email="ana@easelabs.com.br", password="x")


@pytest.fixture
def cliente(ana):
    cliente = APIClient()
    cliente.force_authenticate(ana)
    return cliente


@pytest.fixture
def conversa(ana):
    return Conversation.objects.create(user=ana)


def _xlsx() -> bytes:
    livro = Workbook()
    livro.active.append(["Rede", "UF"])
    livro.active.append(["Pague Menos", "CE"])
    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()


def _png(largura=1920, altura=1080) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (largura, altura), (10, 10, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


def _subir(cliente, conversa, nome, dados):
    return cliente.post(
        "/api/anexos/",
        {"arquivo": SimpleUploadedFile(nome, dados)},
        format="multipart",
    )


def test_planilha_sobe_e_volta_so_a_etiqueta(cliente, conversa):
    r = _subir(cliente, conversa, "redes.xlsx", _xlsx())

    assert r.status_code == 201
    corpo = r.json()
    assert corpo["tipo"] == "planilha"
    assert corpo["detalhe"] == {"linhas": 1, "colunas": ["Rede", "UF"]}
    assert "Pague Menos" in corpo["resumo"]  # a amostra, que é pequena
    assert deposito.buscar(corpo["token"]) is not None


def test_subir_nao_cria_mensagem_nem_grava_arquivo(cliente, conversa):
    """O arquivo não é da conversa até a pergunta sair — e nunca é gravado."""
    _subir(cliente, conversa, "redes.xlsx", _xlsx())

    assert Message.objects.count() == 0


def test_imagem_e_guardada_ja_reduzida(cliente, conversa):
    r = _subir(cliente, conversa, "print.png", _png())

    corpo = r.json()
    assert corpo["tipo"] == "imagem"
    assert max(corpo["detalhe"]["largura"], corpo["detalhe"]["altura"]) == 1280
    guardada = Image.open(io.BytesIO(deposito.buscar(corpo["token"])))
    assert max(guardada.size) == 1280


def test_arquivo_acima_de_5_mb_e_recusado_antes_de_ler(cliente, conversa):
    r = _subir(cliente, conversa, "grande.csv", b"a" * (MAX_BYTES + 1))

    assert r.status_code == 400
    assert "5 MB" in r.json()["error"]


def test_arquivo_disfarcado_de_imagem_e_recusado(cliente, conversa):
    r = _subir(cliente, conversa, "foto.png", b"MZ isto e um executavel")

    assert r.status_code == 400


def test_sem_arquivo_e_400(cliente, conversa):
    r = cliente.post("/api/anexos/", {}, format="multipart")

    assert r.status_code == 400


def test_anexo_de_outra_pessoa_nao_entra_na_conversa_alheia(cliente, django_user_model, monkeypatch):
    """O token não prende o anexo a ninguém; quem prende é a conversa. Postar
    a pergunta numa conversa de outra pessoa continua dando 404."""
    monkeypatch.setattr("messaging.views.process_message.delay", lambda *a, **k: None)
    bia = django_user_model.objects.create_user("bia", password="x")
    alheia = Conversation.objects.create(user=bia)
    etiqueta = _subir(cliente, None, "redes.xlsx", _xlsx()).json()

    r = cliente.post(
        f"/api/conversations/{alheia.pk}/messages/",
        {"client_message_id": "c-1", "text": "oi", "anexo": etiqueta},
        format="json",
    )

    assert r.status_code == 404
    assert Message.objects.count() == 0


def test_subida_exige_login(conversa):
    r = _subir(APIClient(), conversa, "redes.xlsx", _xlsx())

    assert r.status_code == 403


def test_subir_nao_cria_conversa(cliente):
    """Anexar e desistir não pode deixar conversa vazia na lateral."""
    _subir(cliente, None, "redes.xlsx", _xlsx())

    assert Conversation.objects.count() == 0


def test_pergunta_com_anexo_guarda_so_a_etiqueta(cliente, conversa, monkeypatch):
    """A pergunta leva o anexo; a mensagem guarda tipo, nome, resumo e token —
    o conteúdo do arquivo não entra no banco."""
    monkeypatch.setattr("messaging.views.process_message.delay", lambda *a, **k: None)
    etiqueta = _subir(cliente, conversa, "redes.xlsx", _xlsx()).json()

    r = cliente.post(
        f"/api/conversations/{conversa.pk}/messages/",
        {"client_message_id": "c-1", "text": "preencha o sell-out", "anexo": etiqueta},
        format="json",
    )

    assert r.status_code == 202
    mensagem = Message.objects.get()
    assert (mensagem.anexo_tipo, mensagem.anexo_nome) == ("planilha", "redes.xlsx")
    assert mensagem.anexo_token == etiqueta["token"]
    lista = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"]
    assert lista[0]["anexo"] == {"tipo": "planilha", "nome": "redes.xlsx", "planilha_pronta": False}


def _pergunta_preenchida(conversa, dados=b"conteudo preenchido"):
    return Message.objects.create(
        conversation=conversa,
        direction=Message.Direction.INBOUND,
        content="preencha",
        client_message_id="c-1",
        anexo_tipo=Message.Anexo.PLANILHA,
        anexo_nome="redes.xlsx",
        anexo_resposta_token=deposito.guardar(dados),
        anexo_resposta_nome="redes.xlsx",
    )


def test_planilha_preenchida_e_baixada(cliente, conversa):
    pergunta = _pergunta_preenchida(conversa)

    r = cliente.get(f"/api/conversations/{conversa.pk}/messages/{pergunta.pk}/planilha/")

    assert r.status_code == 200
    assert r.content == b"conteudo preenchido"
    assert "jarvis_preenchida_redes.xlsx" in r["Content-Disposition"]


def test_planilha_vencida_devolve_404_com_explicacao(cliente, conversa):
    pergunta = _pergunta_preenchida(conversa)
    deposito.descartar(pergunta.anexo_resposta_token)

    r = cliente.get(f"/api/conversations/{conversa.pk}/messages/{pergunta.pk}/planilha/")

    assert r.status_code == 404
    assert "expirou" in r.json()["error"]


def test_planilha_de_outra_pessoa_nao_e_baixada(conversa, django_user_model):
    pergunta = _pergunta_preenchida(conversa)
    bia = APIClient()
    bia.force_authenticate(django_user_model.objects.create_user("bia", password="x"))

    r = bia.get(f"/api/conversations/{conversa.pk}/messages/{pergunta.pk}/planilha/")

    assert r.status_code == 404


def test_upload_do_tamanho_limite_nao_vai_para_o_disco(settings):
    """O Django grava em arquivo temporário o que passa do teto de memória;
    aqui o teto cobre o maior anexo aceito, então nada toca o disco."""
    assert settings.FILE_UPLOAD_MAX_MEMORY_SIZE >= MAX_BYTES


def test_resposta_aponta_a_planilha_preenchida_da_pergunta(cliente, conversa):
    pergunta = _pergunta_preenchida(conversa)
    Message.objects.create(
        conversation=conversa, direction=Message.Direction.OUTBOUND,
        content="Preenchi 2 de 3 linhas.", client_message_id="out-1", in_reply_to=pergunta,
    )

    lista = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"]

    assert lista[1]["planilha_preenchida"] == {"pergunta": pergunta.pk, "nome": "redes.xlsx"}
