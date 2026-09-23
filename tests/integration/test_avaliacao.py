"""👍/👎 nas respostas e o caminho até virar caso de validação.

Até 2026-09-23 um erro do Jarvis só aparecia quando alguém lia as conversas
no banco à mão. Estes testes seguram o circuito inteiro: a pessoa avalia na
tela, o 👎 vira rascunho de caso num arquivo que a suíte lê, e o relatório
conta.
"""

from datetime import timedelta

import pytest
import yaml
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from conversations.models import Conversation
from datasource.executors.fake import FakeQueryExecutor, make_result
from messaging.models import Avaliacao, Message
from reporting import casos_do_uso
from reporting.cases import load_cases, load_casos_do_uso
from reporting.services import montar_relatorio
from tests.fakes.providers import ScriptedAIProvider, plano, resposta
from tests.unit.test_orchestrator import _responder, catalogo  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(django_user_model):
    return django_user_model.objects.create_user("ana", password="x")


@pytest.fixture
def cliente(ana):
    cliente = APIClient()
    cliente.force_authenticate(ana)
    return cliente


@pytest.fixture
def conversa(ana):
    return Conversation.objects.create(user=ana)


def _pergunta(conversa, texto, client_id):
    return Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND, content=texto,
        client_message_id=client_id, status=Message.Status.RECEIVED,
    )


def _respondida(conversa, catalogo, texto="Vendas de setembro", client_id="c-1", **plano_campos):
    reply = _responder(
        _pergunta(conversa, texto, client_id), catalogo,
        provider=ScriptedAIProvider([plano(reference_query_id="B17", **plano_campos)],
                                    [resposta("Foram 4.306 unidades.")]),
        executor=FakeQueryExecutor([make_result(("und",), [(4306,)])]),
    )
    return reply.message.replies.get()


def _url(conversa, mensagem):
    return f"/api/conversations/{conversa.pk}/messages/{mensagem.pk}/avaliacao/"


def test_avaliar_trocar_e_desfazer(cliente, conversa, catalogo):
    saida = _respondida(conversa, catalogo)

    cliente.put(_url(conversa, saida), {"nota": "down", "comentario": "faltou o  MP"}, format="json")
    assert Avaliacao.objects.get().comentario == "faltou o MP"

    # 👍 depois do 👎 não leva o comentário antigo junto.
    cliente.put(_url(conversa, saida), {"nota": "up", "comentario": "x"}, format="json")
    avaliacao = Avaliacao.objects.get()
    assert (avaliacao.nota, avaliacao.comentario) == ("up", "")

    assert cliente.delete(_url(conversa, saida)).status_code == 204
    assert not Avaliacao.objects.exists()


def test_a_tela_recebe_a_avaliacao_da_resposta(cliente, conversa, catalogo):
    """Sem isto, o 👎 sumia no F5 e a pessoa avaliava de novo."""
    saida = _respondida(conversa, catalogo)
    cliente.put(_url(conversa, saida), {"nota": "down", "comentario": "período errado"}, format="json")

    mensagens = cliente.get(f"/api/conversations/{conversa.pk}/messages/").json()["messages"]

    assert mensagens[1]["avaliacao"] == {"nota": "down", "comentario": "período errado"}
    assert "avaliacao" not in mensagens[0]


def test_nota_invalida_e_pergunta_nao_se_avaliam(cliente, conversa, catalogo):
    saida = _respondida(conversa, catalogo)

    assert cliente.put(_url(conversa, saida), {"nota": "talvez"}, format="json").status_code == 400
    assert cliente.put(_url(conversa, saida.in_reply_to), {"nota": "up"}, format="json").status_code == 404


def test_ninguem_avalia_a_conversa_dos_outros(conversa, catalogo, django_user_model):
    saida = _respondida(conversa, catalogo)
    outro = APIClient()
    outro.force_authenticate(django_user_model.objects.create_user("beto", password="x"))

    assert outro.put(_url(conversa, saida), {"nota": "down"}, format="json").status_code == 404
    assert not Avaliacao.objects.exists()


# ------------------------------------------------------------ 👎 vira caso


def test_rascunho_traz_pergunta_contexto_referencia_e_o_que_estava_errado(conversa, catalogo):
    _respondida(conversa, catalogo, "Vendas deste mês contra o anterior")
    saida = _respondida(conversa, catalogo, "Considere Extras e MP também", client_id="c-2",
                        entendimento="Vendas 1–20/09 × 1–20/08 com Extras e MP")
    avaliacao = Avaliacao.objects.create(message=saida, nota="down", comentario="devolveu o mesmo número")

    caso = casos_do_uso.rascunho(avaliacao)

    assert caso["id"].startswith(f"U{saida.pk}-considere-extras")
    assert caso["grupo"] == "seguimento" and caso["rascunho"] is True
    assert caso["antes"] == ["Vendas deste mês contra o anterior"]
    assert caso["referencia"] == "B17"
    assert "devolveu o mesmo número" in caso["nota"] and "com Extras e MP" in caso["nota"]


def test_comando_grava_rascunhos_que_a_suite_le_e_nao_repete(conversa, catalogo, tmp_path):
    saida = _respondida(conversa, catalogo)
    Avaliacao.objects.create(message=saida, nota="down", comentario="período errado")
    Avaliacao.objects.create(message=_respondida(conversa, catalogo, "outra", client_id="c-2"), nota="up")
    arquivo = tmp_path / "casos_do_uso.yaml"

    call_command("casos_do_uso", saida=str(arquivo))
    call_command("casos_do_uso", saida=str(arquivo))     # nada novo: não duplica

    casos = load_casos_do_uso(arquivo)
    assert len(casos) == 1 and casos[0].rascunho
    assert Avaliacao.objects.get(nota="down").caso_exportado_em is not None
    assert yaml.safe_load(arquivo.read_text(encoding="utf-8"))["casos"][0]["esperado"] == "answer_with_data"


def test_suite_junta_os_casos_do_uso_aos_de_validacao(tmp_path):
    arquivo = tmp_path / "uso.yaml"
    arquivo.write_text(
        "casos:\n  - id: U1-teste\n    grupo: referencia\n    pergunta: vendas\n"
        "    esperado: answer_with_data\n    rascunho: true\n",
        encoding="utf-8",
    )

    suite = load_cases(uso=arquivo)

    assert suite.casos[-1].id == "U1-teste" and suite.casos[-1].rascunho


def test_relatorio_conta_as_avaliacoes_e_a_taxa_de_reescrita(conversa, catalogo):
    saida = _respondida(conversa, catalogo)
    Avaliacao.objects.create(message=saida, nota="down", comentario="faltou MP")

    # `fim` é exclusivo; no Windows o relógio anda em saltos de ~15 ms e a
    # avaliação podia cair no mesmo instante.
    r = montar_relatorio(fim=timezone.now() + timedelta(minutes=1))

    assert (r.uteis, r.erradas) == (0, 1)
    assert r.comentarios[0].motivo == "faltou MP"
    assert r.redigidas == 1 and r.taxa_de_reescrita == 0
