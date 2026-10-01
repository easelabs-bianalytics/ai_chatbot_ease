"""Um arquivo por resposta (2026-10-01).

A resposta a uma planilha anexada trazia a tabela longa com o seu próprio
xlsx e, ao lado, a planilha preenchida: dois arquivos para baixar, o mesmo
dado. Na tela, "Baixar Excel desta tabela" e "Baixar Excel" lado a lado. A
regra agora: com a planilha da pessoa preenchida, ela é O arquivo.
"""

import pytest

from ai_orchestrator.models import AIReply
from attachments import deposito
from conversations.models import Conversation
from datasource.executors.fake import FakeQueryExecutor
from datasource.models import QueryRun
from messaging.models import Message
from whatsapp import saida

pytestmark = pytest.mark.django_db

LINHAS = [[f"0028575300{i:04d}", "VENANCIO", "RIO DE JANEIRO"] for i in range(40)]


def _resposta(user, com_planilha: bool):
    conversa = Conversation.objects.create(user=user, title="pdvs")
    pergunta = Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND, content="preencha a planilha",
        client_message_id="c-1",
        anexo_resposta_token=deposito.guardar(b"PK-planilha") if com_planilha else "",
        anexo_resposta_nome="pdvs.xlsx" if com_planilha else "",
    )
    reply = AIReply.objects.create(
        message=pergunta, decision=AIReply.Decision.ANSWERED,
        raw_response={
            "blocos": [{"tipo": "texto", "texto": "Seguem os PDVs."}, {"tipo": "tabela", "consulta": 0}],
            "dados_blocos": {"0": {"columns": ["cnpj", "rede", "cidade"], "rows": LINHAS, "total": 500,
                                   "truncado": True, "sql": "SELECT 1"}},
        },
    )
    QueryRun.objects.create(
        ai_reply=reply, attempt=1, sql="SELECT 1", guard_result=QueryRun.GuardResult.APPROVED,
        status=QueryRun.Status.SUCCESS, row_count=500, truncated=True,
    )
    return Message.objects.create(
        conversation=conversa, direction=Message.Direction.OUTBOUND, content="Seguem os PDVs.",
        client_message_id="o-1", in_reply_to=pergunta,
    )


def _documentos(envios):
    return [e for e in envios if e.tipo == "documento"]


def test_com_planilha_preenchida_sai_so_ela(django_user_model):
    resposta = _resposta(django_user_model.objects.create_user("ana", password="x"), com_planilha=True)

    envios = saida.montar(resposta, executor=FakeQueryExecutor([]))

    documentos = _documentos(envios)
    assert [d.nome for d in documentos] == ["pdvs.xlsx"]
    texto = "\n".join(e.texto for e in envios if e.tipo == "texto")
    assert "a lista completa está na planilha preenchida, anexada" in texto


def test_sem_planilha_a_tabela_longa_continua_com_o_arquivo_dela(django_user_model):
    resposta = _resposta(django_user_model.objects.create_user("bia", password="x"), com_planilha=False)

    envios = saida.montar(resposta, executor=None)

    assert [d.nome for d in _documentos(envios)] == ["jarvis_tabela_1.xlsx"]
