"""Pedido para ver a consulta da resposta anterior (2026-10-19).

No WhatsApp, o diretor mandou "me mande a query" e "query sql": a primeira
virou uma conversa que não mandava nada; a segunda rodou a consulta de novo
e disse que ela estava no bloco "Consulta executada", que só existe na web.
O Paulo mandou "Me mostre a query sql" e recebeu um texto sem sentido.
"""

import pytest

from ai_orchestrator.models import AIReply
from ai_orchestrator.orchestrator import handle_message
from ai_orchestrator.rules import pedido_da_consulta
from catalog.loader import load_catalog
from conversations.models import Conversation
from datasource.executors.fake import FakeQueryExecutor, make_result
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta


@pytest.mark.parametrize("texto", [
    "query sql",
    "me mande a query para analisar o output",
    "Me mostre a query sql",
    "qual SQL você usou?",
    "mostra a consulta usada",
    "me passa essa consulta",
])
def test_pedidos_da_consulta_sao_reconhecidos(texto):
    assert pedido_da_consulta(texto)


@pytest.mark.parametrize("texto", [
    "Crie uma query que traga as vendas de 2026 por mês",
    "faça uma consulta das vendas de agosto",
    "Qual o Sell out ease na cidade de Cuiaba nos últimos 3 meses?",
    "quero consultar o market share",
    "consulta de PDVs em SP",
])
def test_perguntas_de_dado_nao_sao_pedido_da_consulta(texto):
    """Pedir para CRIAR uma consulta é pergunta de dado: vai ao modelo."""
    assert not pedido_da_consulta(texto)


@pytest.fixture
def conversa(django_user_model):
    return Conversation.objects.create(user=django_user_model.objects.create_user("fernando", password="x"))


def _mensagem(conversa, texto, cid):
    return Message.objects.create(conversation=conversa, direction=Message.Direction.INBOUND, content=texto,
                                  client_message_id=cid, status=Message.Status.RECEIVED)


@pytest.mark.django_db
def test_devolve_o_sql_da_ultima_resposta_sem_ia_e_sem_rodar_de_novo(conversa):
    sql = "SELECT SUM(und) FROM cddd.vendas_consolidado"
    catalogo = load_catalog()
    handle_message(_mensagem(conversa, "quantas unidades em agosto?", "c-1"), channel=FakeChannel(),
                   provider=ScriptedAIProvider([plano(sql=sql)], [resposta("Foram 47 unidades.")]),
                   executor=FakeQueryExecutor([make_result(("und",), [(47,)])]), catalog=catalogo)

    provider, executor = ScriptedAIProvider([], []), FakeQueryExecutor()
    reply = handle_message(_mensagem(conversa, "query sql", "c-2"), channel=FakeChannel(),
                           provider=provider, executor=executor, catalog=catalogo)

    assert reply.rule == "pedido_da_consulta"
    assert reply.decision == AIReply.Decision.CONVERSATION
    assert f"```sql\n{sql}\n```" in reply.reply_text
    assert "quantas unidades em agosto?" in reply.reply_text
    assert executor.executed == [] and provider.plan_requests == []
    assert not reply.calls.exists()


@pytest.mark.django_db
def test_sem_consulta_na_conversa_diz_isso(conversa):
    reply = handle_message(_mensagem(conversa, "me mande a query", "c-1"), channel=FakeChannel(),
                           provider=ScriptedAIProvider([], []), executor=FakeQueryExecutor(),
                           catalog=load_catalog())

    assert reply.rule == "pedido_da_consulta"
    assert "Ainda não rodei nenhuma consulta" in reply.reply_text


def test_consulta_chega_inteira_no_whatsapp():
    """Dentro do bloco, `||` não vira tabela e `*` não vira itálico; o
    "sql" do ```sql sairia escrito no celular."""
    from whatsapp import formato

    sql = "SELECT 'a ' || sku || ' b' AS x, COUNT(*) AS n\nFROM t\n-- comentario *importante*\nWHERE a = 1"
    texto = formato.de_markdown(f"Esta é a consulta da resposta a **vendas**:\n\n```sql\n{sql}\n```")

    assert texto == f"Esta é a consulta da resposta a *vendas*:\n\n```\n{sql}\n```"


def test_consulta_longa_e_cortada_em_blocos_fechados():
    from whatsapp import formato

    linhas = [f"  AND coluna_{i:03d} = 'valor muito comprido para encher a mensagem {i}'" for i in range(120)]
    partes = formato.dividir("Esta é a consulta:\n\n```\n" + "\n".join(linhas) + "\n```")

    assert len(partes) > 1
    blocos = [p for p in partes if "```" in p]
    assert all(p.count("```") == 2 for p in blocos)
    assert all(len(p) <= formato.MAX_CARACTERES_POR_MENSAGEM for p in partes)
    reunidas = "\n".join(l for p in partes for l in p.split("\n") if l.startswith("  AND"))
    assert reunidas == "\n".join(linhas)
