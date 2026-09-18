"""Projetos (pastas), arquivo e exclusão de conversas (ADR-0018).

Organizar a lista não pode apagar auditoria nem abrir a conversa de um
usuário para outro — é isso que cada teste aqui fixa.
"""

import pytest
from rest_framework.test import APIClient

from conversations.models import Conversation, Project
from messaging.models import Message

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(django_user_model):
    return django_user_model.objects.create_user("ana", password="x")


@pytest.fixture
def bruno(django_user_model):
    return django_user_model.objects.create_user("bruno", password="x")


@pytest.fixture
def cliente(ana):
    client = APIClient()
    client.force_login(ana)
    return client


def _conversa(usuario, titulo="vendas de agosto"):
    return Conversation.objects.create(user=usuario, title=titulo)


# --- arquivar -------------------------------------------------------------


def test_arquivar_mantem_a_conversa_na_lista_com_a_situacao(cliente, ana):
    conversa = _conversa(ana)

    resposta = cliente.patch(f"/api/conversations/{conversa.pk}/", {"status": "archived"}, format="json")

    assert resposta.status_code == 200
    listadas = cliente.get("/api/conversations/").json()["conversations"]
    assert listadas[0]["status"] == "archived"


def test_perguntar_numa_conversa_arquivada_tira_ela_do_arquivo(cliente, ana):
    """Senão a resposta chegaria num lugar escondido da lista."""
    conversa = _conversa(ana)
    conversa.status = Conversation.Status.ARCHIVED
    conversa.save()

    cliente.post(
        f"/api/conversations/{conversa.pk}/messages/",
        {"client_message_id": "c-1", "text": "e em setembro?"},
        format="json",
    )

    conversa.refresh_from_db()
    assert conversa.status == Conversation.Status.OPEN


def test_situacao_desconhecida_e_recusada(cliente, ana):
    conversa = _conversa(ana)

    resposta = cliente.patch(f"/api/conversations/{conversa.pk}/", {"status": "lixeira"}, format="json")

    assert resposta.status_code == 400


def test_renomear_conversa(cliente, ana):
    conversa = _conversa(ana)

    cliente.patch(f"/api/conversations/{conversa.pk}/", {"title": "  Fechamento   agosto "}, format="json")

    conversa.refresh_from_db()
    assert conversa.title == "Fechamento agosto"


def test_titulo_vazio_e_recusado(cliente, ana):
    conversa = _conversa(ana)

    assert cliente.patch(f"/api/conversations/{conversa.pk}/", {"title": "  "}, format="json").status_code == 400


# --- excluir --------------------------------------------------------------


def test_excluir_some_da_lista_e_da_tela(cliente, ana):
    conversa = _conversa(ana)

    assert cliente.delete(f"/api/conversations/{conversa.pk}/").status_code == 204
    assert cliente.get("/api/conversations/").json()["conversations"] == []
    assert cliente.get(f"/api/conversations/{conversa.pk}/messages/").status_code == 404


def test_excluir_nao_apaga_a_auditoria(cliente, ana):
    """A pergunta, a consulta e o custo ficam para a auditoria (FR-15);
    apagar de verdade é decisão da política de retenção (O-08)."""
    conversa = _conversa(ana)
    Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND, content="p", client_message_id="c"
    )

    cliente.delete(f"/api/conversations/{conversa.pk}/")

    conversa.refresh_from_db()
    assert conversa.deleted_at is not None
    assert conversa.messages.count() == 1


def test_conversa_de_outro_usuario_nao_se_mexe(cliente, bruno):
    """404, e não 403: não confirma que a conversa existe."""
    alheia = _conversa(bruno)

    assert cliente.patch(f"/api/conversations/{alheia.pk}/", {"status": "archived"}, format="json").status_code == 404
    assert cliente.delete(f"/api/conversations/{alheia.pk}/").status_code == 404
    alheia.refresh_from_db()
    assert alheia.deleted_at is None


# --- projetos -------------------------------------------------------------


def test_criar_projeto_e_mover_conversa_para_ele(cliente, ana):
    conversa = _conversa(ana)

    projeto = cliente.post("/api/projects/", {"name": "Território Sul"}, format="json").json()
    cliente.patch(f"/api/conversations/{conversa.pk}/", {"project": projeto["id"]}, format="json")

    assert cliente.get("/api/projects/").json()["projects"] == [
        {"id": projeto["id"], "name": "Território Sul", "created_at": projeto["created_at"]}
    ]
    assert cliente.get("/api/conversations/").json()["conversations"][0]["project"] == projeto["id"]


def test_tirar_conversa_do_projeto(cliente, ana):
    projeto = Project.objects.create(user=ana, name="Sul")
    conversa = _conversa(ana)
    conversa.project = projeto
    conversa.save()

    cliente.patch(f"/api/conversations/{conversa.pk}/", {"project": None}, format="json")

    conversa.refresh_from_db()
    assert conversa.project is None


def test_nao_da_para_usar_o_projeto_de_outro_usuario(cliente, ana, bruno):
    alheio = Project.objects.create(user=bruno, name="do bruno")
    conversa = _conversa(ana)

    resposta = cliente.patch(f"/api/conversations/{conversa.pk}/", {"project": alheio.pk}, format="json")

    assert resposta.status_code == 404
    assert cliente.get("/api/projects/").json()["projects"] == []


def test_projeto_sem_nome_e_recusado(cliente):
    assert cliente.post("/api/projects/", {"name": "   "}, format="json").status_code == 400


def test_renomear_projeto(cliente, ana):
    projeto = Project.objects.create(user=ana, name="Sul")

    cliente.patch(f"/api/projects/{projeto.pk}/", {"name": "Região Sul"}, format="json")

    projeto.refresh_from_db()
    assert projeto.name == "Região Sul"


def test_excluir_projeto_devolve_as_conversas_para_a_lista(cliente, ana):
    """Quem exclui a pasta está reorganizando, não jogando conversa fora."""
    projeto = Project.objects.create(user=ana, name="Sul")
    conversa = _conversa(ana)
    conversa.project = projeto
    conversa.save()

    assert cliente.delete(f"/api/projects/{projeto.pk}/").status_code == 204

    conversa.refresh_from_db()
    assert conversa.project is None
    assert conversa.deleted_at is None


def test_organizar_nao_muda_a_data_da_conversa(cliente, ana):
    """A lista é ordenada pela última atividade: mover para uma pasta ou
    arquivar não pode fazer uma conversa antiga parecer de hoje."""
    conversa = _conversa(ana)
    Conversation.objects.filter(pk=conversa.pk).update(updated_at="2026-01-10T12:00:00Z")
    projeto = Project.objects.create(user=ana, name="Sul")

    cliente.patch(f"/api/conversations/{conversa.pk}/", {"project": projeto.pk}, format="json")
    cliente.patch(f"/api/conversations/{conversa.pk}/", {"status": "archived"}, format="json")

    conversa.refresh_from_db()
    assert conversa.updated_at.isoformat().startswith("2026-01-10")
