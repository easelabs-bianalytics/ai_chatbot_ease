"""Os arquivos ficam com a conversa (ADR-0034).

Até 2026-10-05 o anexo e a planilha devolvida viviam só no Redis da task,
por até duas horas, e todo deploy apagava os de todo mundo. Em 2026-10-05
subiram umas cinco versões, e quem trabalhava com uma planilha perdeu o
"Baixar Excel" das respostas sobre ela, a continuação da conversa e a chance
de auditar a resposta. Aqui o deploy é simulado limpando o cache: o arquivo
tem de continuar lá, vindo do armazém (o S3 em produção, memória no teste).
"""

import io

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APIClient

from attachments import deposito
from attachments.armazem import armazem
from conversations.models import Conversation
from messaging.models import ArquivoDaConversa, Message

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


def _gerar_xlsx() -> bytes:
    livro = Workbook()
    livro.active.append(["Rede", "UF"])
    livro.active.append(["Pague Menos", "CE"])
    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()


# Gerada uma vez: o openpyxl grava a hora de criação dentro do arquivo, e duas
# planilhas geradas em segundos diferentes não são iguais byte a byte — o que
# fazia a comparação falhar de vez em quando.
XLSX = _gerar_xlsx()


def _xlsx() -> bytes:
    return XLSX


def _pergunta_com_planilha(cliente, conversa, monkeypatch):
    monkeypatch.setattr("messaging.views.process_message.delay", lambda *a, **k: None)
    etiqueta = cliente.post("/api/anexos/", {"arquivo": SimpleUploadedFile("redes.xlsx", _xlsx())},
                            format="multipart").json()
    cliente.post(f"/api/conversations/{conversa.pk}/messages/",
                 {"client_message_id": "c-1", "text": "preencha o sell-out", "anexo": etiqueta}, format="json")
    return Message.objects.get(direction=Message.Direction.INBOUND)


def test_anexo_enviado_fica_na_pasta_da_conversa(cliente, conversa, monkeypatch):
    pergunta = _pergunta_com_planilha(cliente, conversa, monkeypatch)

    arquivo = ArquivoDaConversa.objects.get()
    assert (arquivo.conversation, arquivo.message, arquivo.papel) == (conversa, pergunta, "entrada")
    assert arquivo.token == pergunta.anexo_token
    assert arquivo.chave == f"conversas/{conversa.pk}/{pergunta.anexo_token}"
    assert armazem().buscar(arquivo.chave) == _xlsx()


def test_deploy_nao_apaga_o_anexo(cliente, conversa, monkeypatch):
    """O deploy recria a task e o Redis junto. O arquivo volta do armazém, e
    a pessoa baixa de novo o que mandou."""
    pergunta = _pergunta_com_planilha(cliente, conversa, monkeypatch)
    cache.clear()

    assert deposito.buscar(pergunta.anexo_token) == _xlsx()
    r = cliente.get(f"/api/conversations/{conversa.pk}/messages/{pergunta.pk}/anexo/")
    assert r.status_code == 200 and r.content == _xlsx()
    assert 'filename="redes.xlsx"' in r["Content-Disposition"]


def test_planilha_devolvida_sobrevive_ao_deploy(cliente, conversa):
    pergunta = Message.objects.create(conversation=conversa, direction=Message.Direction.INBOUND,
                                      content="preencha", client_message_id="c-1",
                                      anexo_tipo=Message.Anexo.PLANILHA, anexo_nome="redes.xlsx")
    token = deposito.guardar(b"preenchida")
    assert deposito.fixar(token, conversa=conversa, mensagem=pergunta,
                          papel=ArquivoDaConversa.Papel.SAIDA, nome="redes.xlsx")
    Message.objects.filter(pk=pergunta.pk).update(anexo_resposta_token=token, anexo_resposta_nome="redes.xlsx")
    cache.clear()

    r = cliente.get(f"/api/conversations/{conversa.pk}/messages/{pergunta.pk}/planilha/")

    assert r.status_code == 200 and r.content == b"preenchida"


def test_apagar_a_conversa_apaga_os_arquivos_de_verdade(cliente, conversa, monkeypatch):
    """A conversa some da lista por exclusão lógica (ADR-0018), mas os
    arquivos — dado pessoal de médico e de paciente — saem do armazém."""
    pergunta = _pergunta_com_planilha(cliente, conversa, monkeypatch)
    chave = ArquivoDaConversa.objects.get().chave

    assert cliente.delete(f"/api/conversations/{conversa.pk}/").status_code == 204

    assert armazem().buscar(chave) is None
    assert not ArquivoDaConversa.objects.exists()
    assert deposito.buscar(pergunta.anexo_token) is None


def test_ninguem_baixa_o_anexo_da_conversa_dos_outros(conversa, ana, monkeypatch, django_user_model):
    dono = APIClient()
    dono.force_authenticate(ana)
    pergunta = _pergunta_com_planilha(dono, conversa, monkeypatch)
    outro = APIClient()
    outro.force_authenticate(django_user_model.objects.create_user("beto", password="x"))

    assert outro.get(f"/api/conversations/{conversa.pk}/messages/{pergunta.pk}/anexo/").status_code == 404


def test_armazem_fora_do_ar_nao_impede_a_pergunta(cliente, conversa, monkeypatch):
    """Guardar é garantia a mais, nunca condição: com o S3 fora, a pergunta
    segue como antes, com o arquivo só no Redis."""
    def falha(*_a, **_k):
        raise RuntimeError("S3 indisponível")

    monkeypatch.setattr(armazem(), "guardar", falha)

    pergunta = _pergunta_com_planilha(cliente, conversa, monkeypatch)

    assert pergunta.anexo_token
    assert deposito.buscar(pergunta.anexo_token) == _xlsx()
    assert not ArquivoDaConversa.objects.exists()


def test_mesmo_arquivo_nao_e_guardado_duas_vezes(conversa):
    token = deposito.guardar(b"x")
    deposito.fixar(token, conversa=conversa, papel=ArquivoDaConversa.Papel.ENTRADA)
    deposito.fixar(token, conversa=conversa, papel=ArquivoDaConversa.Papel.ENTRADA)

    assert ArquivoDaConversa.objects.count() == 1


def test_producao_sem_bucket_nao_finge_que_guardou(conversa, settings, monkeypatch):
    """Sem JARVIS_ARQUIVOS_BUCKET em produção, guardar em memória deixaria o
    registro apontando para um arquivo que só um processo vê e que some no
    próximo deploy. O arquivo segue só no Redis, como antes, e nada é
    registrado."""
    from attachments import armazem as modulo

    settings.ARMAZEM_EM_MEMORIA = False
    settings.DEBUG = False
    modulo.armazem.cache_clear()
    token = deposito.guardar(b"x")

    assert isinstance(modulo.armazem(), modulo.ArmazemDesligado)
    assert not deposito.fixar(token, conversa=conversa, papel=ArquivoDaConversa.Papel.ENTRADA)
    assert not ArquivoDaConversa.objects.exists()
    assert deposito.buscar(token) == b"x"



# ------------------------------------------------ download pelo Admin


def _arquivo_guardado(conversa, dados=b"conteudo da planilha", nome="redes.xlsx"):
    token = deposito.guardar(dados)
    assert deposito.fixar(token, conversa=conversa, papel=ArquivoDaConversa.Papel.ENTRADA, nome=nome)
    return ArquivoDaConversa.objects.get(token=token)


def _admin(django_user_model, superusuario=True):
    usuario = django_user_model.objects.create_user("bi", password="x", is_staff=True, is_superuser=superusuario)
    cliente = APIClient()
    cliente.force_login(usuario)
    return cliente


def test_admin_baixa_o_arquivo_com_o_nome_original(conversa, django_user_model, caplog):
    """No S3 o arquivo se chama só pelo token. O Admin devolve com o nome e o
    tipo originais — depois de um deploy, vindo do S3 — e registra quem
    baixou: são dados pessoais."""
    arquivo = _arquivo_guardado(conversa)
    cache.clear()

    with caplog.at_level("INFO", logger="messaging.admin"):
        r = _admin(django_user_model).get(f"/admin/messaging/arquivodaconversa/{arquivo.pk}/baixar/")

    assert r.status_code == 200 and r.content == b"conteudo da planilha"
    assert r["Content-Type"].startswith("application/vnd.openxmlformats")
    assert 'filename="redes.xlsx"' in r["Content-Disposition"]
    assert "bi baixou o arquivo" in caplog.text


def test_lista_do_admin_tem_o_link_de_baixar(conversa, django_user_model):
    arquivo = _arquivo_guardado(conversa)

    r = _admin(django_user_model).get("/admin/messaging/arquivodaconversa/")

    assert f"/admin/messaging/arquivodaconversa/{arquivo.pk}/baixar/" in r.content.decode()


def test_arquivo_que_ja_foi_apagado_avisa_em_vez_de_baixar_vazio(conversa, django_user_model):
    arquivo = _arquivo_guardado(conversa)
    armazem().apagar([arquivo.chave])
    cache.clear()

    r = _admin(django_user_model).get(f"/admin/messaging/arquivodaconversa/{arquivo.pk}/baixar/")

    assert r.status_code == 302


def test_sem_permissao_de_ver_os_arquivos_nao_baixa(conversa, django_user_model):
    """Equipe do Admin sem a permissão destes registros não baixa planilha
    de ninguém."""
    arquivo = _arquivo_guardado(conversa)

    r = _admin(django_user_model, superusuario=False).get(
        f"/admin/messaging/arquivodaconversa/{arquivo.pk}/baixar/")

    assert r.status_code == 403


def test_quem_nao_e_da_equipe_e_mandado_para_o_login(conversa, ana):
    arquivo = _arquivo_guardado(conversa)
    cliente = APIClient()
    cliente.force_login(ana)

    r = cliente.get(f"/admin/messaging/arquivodaconversa/{arquivo.pk}/baixar/")

    assert r.status_code == 302 and "login" in r["Location"]
