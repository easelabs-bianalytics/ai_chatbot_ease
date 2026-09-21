"""Download da planilha de uma resposta (ADR-0020).

O endpoint roda de novo a consulta que a resposta usou, com um limite maior
que o da conversa. É o único caminho pelo qual muita linha sai da
ferramenta: os testes aqui fixam quem pode baixar, o que é validado antes de
ir ao banco e o que fica registrado.
"""

import io

import pytest
from openpyxl import load_workbook
from rest_framework.test import APIClient

from ai_orchestrator.models import AIReply
from conversations.models import Conversation
from datasource.executors.base import QueryExecutionError
from datasource.executors.fake import FakeQueryExecutor, make_result
from datasource.models import DataExport, QueryRun
from messaging.models import Message

pytestmark = pytest.mark.django_db

SQL = "SELECT mes, total_und FROM cddd.vendas_consolidado"
RESULTADO = make_result(("mes", "total_und"), [("2026-07", 761), ("2026-08", 777)], duration_ms=42)


@pytest.fixture
def ana(django_user_model):
    return django_user_model.objects.create_user("ana", password="x")


@pytest.fixture
def cliente(ana):
    client = APIClient()
    client.force_login(ana)
    return client


@pytest.fixture
def resposta(ana):
    """Uma pergunta respondida com dado: é o que tem planilha para baixar."""
    conversa = Conversation.objects.create(user=ana, title="unidades por mês")
    pergunta = Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND,
        content="quantas unidades por mês em 2026?", client_message_id="c-1",
    )
    saida = Message.objects.create(
        conversation=conversa, direction=Message.Direction.OUTBOUND,
        content="Foram 777 unidades em ago/2026.", client_message_id="o-1", in_reply_to=pergunta,
    )
    reply = AIReply.objects.create(message=pergunta, decision=AIReply.Decision.ANSWERED)
    QueryRun.objects.create(
        ai_reply=reply, attempt=1, sql=SQL, reference_query_id="B04",
        guard_result=QueryRun.GuardResult.APPROVED, status=QueryRun.Status.SUCCESS,
        row_count=2, duration_ms=42,
    )
    return saida


def _url(mensagem):
    return f"/api/conversations/{mensagem.conversation_id}/messages/{mensagem.pk}/excel/"


def _executor(monkeypatch, executor):
    monkeypatch.setattr("messaging.views.get_configured_executor", lambda: executor)
    return executor


def test_download_devolve_a_planilha_com_os_dados_da_consulta(cliente, resposta, monkeypatch):
    executor = _executor(monkeypatch, FakeQueryExecutor([RESULTADO]))

    r = cliente.get(_url(resposta))

    assert r.status_code == 200
    assert r["Content-Type"].endswith("spreadsheetml.sheet")
    assert ".xlsx" in r["Content-Disposition"]
    aba = load_workbook(io.BytesIO(r.content))["Dados"]
    assert [c.value for c in aba[1]] == ["Mes", "Total und"]
    assert aba["B3"].value == 777
    # O validador embrulha a consulta com o limite da planilha antes de ela
    # ir ao banco — é por isso que ele roda de novo aqui.
    assert SQL in executor.executed[0]
    assert "LIMIT 50001" in executor.executed[0]


def test_a_consulta_passa_pelo_validador_de_novo_com_o_limite_da_planilha(cliente, resposta, monkeypatch):
    """O limite da conversa é pequeno porque o resultado vai para a IA; o da
    planilha não passa pela IA e pode ser maior. Quem garante que continua
    sendo um SELECT é o validador, rodando de novo."""
    from messaging import views

    chamadas = []
    original = views.validate_sql
    monkeypatch.setattr(views, "validate_sql", lambda sql, cat, **kw: chamadas.append(kw) or original(sql, cat, **kw))
    _executor(monkeypatch, FakeQueryExecutor([RESULTADO]))

    cliente.get(_url(resposta))

    assert chamadas == [{"max_rows": views.EXPORT_MAX_ROWS}]
    assert views.EXPORT_MAX_ROWS > 500


def test_cada_download_fica_registrado(cliente, resposta, ana, monkeypatch):
    _executor(monkeypatch, FakeQueryExecutor([RESULTADO]))

    cliente.get(_url(resposta))

    registro = DataExport.objects.get()
    assert registro.user == ana
    assert registro.message == resposta
    assert registro.status == DataExport.Status.OK
    assert registro.row_count == 2
    assert registro.sql == SQL


def test_erro_do_banco_vira_aviso_e_fica_registrado(cliente, resposta, monkeypatch):
    _executor(monkeypatch, FakeQueryExecutor([QueryExecutionError("conexão caiu")]))

    r = cliente.get(_url(resposta))

    assert r.status_code == 502
    assert "planilha" in r.json()["error"]
    assert DataExport.objects.get().status == DataExport.Status.ERROR


def test_resposta_sem_consulta_nao_tem_o_que_exportar(cliente, ana, monkeypatch):
    """Conversa, esclarecimento e "não sei" não rodaram nada no banco."""
    conversa = Conversation.objects.create(user=ana)
    saida = Message.objects.create(
        conversation=conversa, direction=Message.Direction.OUTBOUND,
        content="Sou o Jarvis, copiloto de dados da Ease Labs.", client_message_id="o-9",
    )

    r = cliente.get(_url(saida))

    assert r.status_code == 404
    assert DataExport.objects.count() == 0


def test_conversa_de_outro_usuario_nao_abre(django_user_model, resposta):
    """Mesmo sabendo o id: a planilha leva dados de negócio inteiros."""
    bruno = django_user_model.objects.create_user("bruno", password="x")
    outro = APIClient()
    outro.force_login(bruno)

    assert outro.get(_url(resposta)).status_code == 404


def test_sem_login_nao_baixa(resposta):
    assert APIClient().get(_url(resposta)).status_code in (401, 403)


# --- o que a tela recebe ---------------------------------------------------


def _mensagens(cliente, mensagem):
    r = cliente.get(f"/api/conversations/{mensagem.conversation_id}/messages/")
    return {m["id"]: m for m in r.json()["messages"]}


def test_resposta_com_dado_oferece_a_planilha(cliente, resposta):
    """Com duas ou mais linhas o botão aparece, mesmo que a resposta seja só
    texto: é o jeito de levar o resultado inteiro. Quando o usuário pediu
    Excel, a tela destaca o botão."""
    fonte = _mensagens(cliente, resposta)[resposta.pk]["fonte"]

    assert fonte["excel"] is True
    assert fonte["excel_pedido"] is False


def test_resultado_de_uma_linha_nao_oferece_planilha(cliente, resposta):
    """Uma linha é um número, e ele já está no texto. Em 2026-09-21 a tela
    mostrava "Baixar Excel" embaixo de "O sell out cresceu de 17.709 para…",
    prometendo uma planilha que não acrescentava nada."""
    QueryRun.objects.filter(ai_reply__message=resposta.in_reply_to).update(row_count=1)

    fonte = _mensagens(cliente, resposta)[resposta.pk]["fonte"]

    assert fonte["excel"] is False


def test_pedido_explicito_de_excel_vence_a_regra_da_linha_unica(cliente, resposta):
    QueryRun.objects.filter(ai_reply__message=resposta.in_reply_to).update(row_count=1)
    reply = AIReply.objects.get(message=resposta.in_reply_to)
    reply.raw_response = {"excel": True}
    reply.save()

    fonte = _mensagens(cliente, resposta)[resposta.pk]["fonte"]

    assert fonte["excel"] is True
    assert fonte["excel_pedido"] is True


def test_grafico_e_dados_chegam_juntos_para_a_tela_desenhar(cliente, resposta):
    reply = AIReply.objects.get(message=resposta.in_reply_to)
    reply.raw_response = {"grafico": {"tipo": "linha", "x": "mes", "series": ["total_und"], "titulo": "Unidades"}}
    reply.save()
    consulta = reply.query_runs.get()
    consulta.result_sample = {"columns": ["mes", "total_und"], "rows": [["2026-07", 761], ["2026-08", 777]]}
    consulta.save()

    fonte = _mensagens(cliente, resposta)[resposta.pk]["fonte"]

    assert fonte["grafico"]["tipo"] == "linha"
    assert fonte["dados"]["rows"] == [["2026-07", 761], ["2026-08", 777]]


def test_sem_grafico_a_tela_nao_recebe_os_dados(cliente, resposta):
    """Mandar o resultado para o navegador sem ninguém desenhar só engorda
    a resposta da API."""
    fonte = _mensagens(cliente, resposta)[resposta.pk]["fonte"]

    assert "grafico" not in fonte
    assert "dados" not in fonte
