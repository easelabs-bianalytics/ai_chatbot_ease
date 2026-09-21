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


# --- busca no histórico ------------------------------------------------------


def test_busca_acha_pelo_titulo_e_pelo_texto_da_pergunta(cliente, ana):
    """Quem procura "ruptura" lembra do que perguntou, não de como a conversa
    ficou nomeada."""
    pelo_titulo = Conversation.objects.create(user=ana, title="Ruptura nos CDs")
    pela_mensagem = Conversation.objects.create(user=ana, title="Conversa de terça")
    Message.objects.create(conversation=pela_mensagem, direction=Message.Direction.INBOUND,
                           content="quais CDs estão em ruptura hoje?", client_message_id="c-1")
    Conversation.objects.create(user=ana, title="Sell out de agosto")

    achadas = cliente.get("/api/conversations/?q=ruptura").json()["conversations"]

    assert {c["id"] for c in achadas} == {pelo_titulo.pk, pela_mensagem.pk}


def test_busca_nao_repete_a_conversa_que_casa_em_varias_mensagens(cliente, ana):
    conversa = Conversation.objects.create(user=ana, title="Estoque")
    for n in range(3):
        Message.objects.create(conversation=conversa, direction=Message.Direction.INBOUND,
                               content="e a ruptura?", client_message_id=f"c-{n}")

    achadas = cliente.get("/api/conversations/?q=ruptura").json()["conversations"]

    assert len(achadas) == 1


def test_busca_nao_alcanca_conversa_de_outro_usuario(cliente, ana, bruno):
    Conversation.objects.create(user=bruno, title="Ruptura do Bruno")
    minha = Conversation.objects.create(user=ana, title="Ruptura minha")

    achadas = cliente.get("/api/conversations/?q=ruptura").json()["conversations"]

    assert [c["id"] for c in achadas] == [minha.pk]


def test_busca_vazia_devolve_tudo(cliente, ana):
    Conversation.objects.create(user=ana, title="Uma")
    Conversation.objects.create(user=ana, title="Outra")

    assert len(cliente.get("/api/conversations/?q=   ").json()["conversations"]) == 2


def test_conversa_excluida_nao_volta_na_busca(cliente, ana):
    conversa = Conversation.objects.create(user=ana, title="Ruptura apagada")
    cliente.delete(f"/api/conversations/{conversa.pk}/")

    assert cliente.get("/api/conversations/?q=ruptura").json()["conversations"] == []


# --- ordem escolhida à mão (arrastar na lista) ----------------------------


def test_ordem_arrastada_manda_na_listagem(cliente, ana):
    """Arrastar precisa valer mais que a última atividade.

    Sem isto a lista volta para a ordem cronológica no próximo F5 e o gesto
    de arrastar vira enfeite."""
    primeira = _conversa(ana, "primeira")
    segunda = _conversa(ana, "segunda")
    terceira = _conversa(ana, "terceira")

    resposta = cliente.patch(
        "/api/conversations/ordem/",
        {"ids": [terceira.pk, primeira.pk, segunda.pk]},
        format="json",
    )

    assert resposta.status_code == 200
    assert resposta.json() == {"ordenadas": 3}
    listadas = [c["id"] for c in cliente.get("/api/conversations/").json()["conversations"]]
    assert listadas == [terceira.pk, primeira.pk, segunda.pk]


def test_conversa_nova_nasce_no_topo_do_que_ja_foi_arrumado(cliente, ana):
    """`position = 0` é "nunca posicionada", e vem antes de 1, 2, 3…

    Se a conversa nova caísse no fim, quem organizou a lista uma vez teria de
    reorganizar a cada pergunta."""
    antiga = _conversa(ana, "antiga")
    cliente.patch("/api/conversations/ordem/", {"ids": [antiga.pk]}, format="json")

    nova = cliente.post("/api/conversations/", {"title": "recém-criada"}, format="json").json()

    listadas = [c["id"] for c in cliente.get("/api/conversations/").json()["conversations"]]
    assert listadas == [nova["id"], antiga.pk]


def test_ordenar_nao_mexe_na_ultima_atividade(cliente, ana):
    """Organizar não é conversar.

    Se `updated_at` subisse junto, arrastar faria toda conversa mexida parecer
    de agora — e "Recentes" deixaria de querer dizer alguma coisa."""
    conversa = _conversa(ana, "vendas")
    antes = Conversation.objects.get(pk=conversa.pk).updated_at

    cliente.patch("/api/conversations/ordem/", {"ids": [conversa.pk]}, format="json")

    assert Conversation.objects.get(pk=conversa.pk).updated_at == antes


def test_ordem_ignora_conversa_de_outro_usuario(cliente, ana, bruno):
    """Mandar o id de outra pessoa não pode reordenar a lista dela."""
    dele = Conversation.objects.create(user=bruno, title="do Bruno", position=7)
    minha = _conversa(ana, "minha")

    resposta = cliente.patch(
        "/api/conversations/ordem/", {"ids": [dele.pk, minha.pk]}, format="json"
    )

    assert resposta.json() == {"ordenadas": 1}
    assert Conversation.objects.get(pk=dele.pk).position == 7


def test_ordem_sem_lista_de_ids_responde_400(cliente):
    resposta = cliente.patch("/api/conversations/ordem/", {"ids": "1,2"}, format="json")

    assert resposta.status_code == 400
