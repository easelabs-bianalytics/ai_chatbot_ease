"""Banco fora do ar não é erro de consulta (achado de 2026-09-21).

Com o túnel caído no meio de um preenchimento, a falha de conexão foi
tratada como SQL errado: a IA foi chamada para "corrigir" uma consulta certa
(US$ 0,094) e a pessoa leu "não consegui montar uma consulta segura".
"""

import psycopg2
import pytest

from ai_orchestrator import canned
from ai_orchestrator.models import AIReply, CatalogGap
from datasource.executors.base import QueryUnavailable
from datasource.executors.fake import FakeQueryExecutor
from datasource.executors.postgres_readonly import PostgresReadOnlyExecutor
from tests.fakes.providers import ScriptedAIProvider, plano
from tests.unit.test_orchestrator import _pergunta, _responder, catalogo, conversa  # noqa: F401

pytestmark = pytest.mark.django_db


def test_banco_fora_do_ar_nao_chama_a_ia_para_corrigir(conversa, catalogo):
    provider = ScriptedAIProvider([plano()])
    executor = FakeQueryExecutor([QueryUnavailable("a conexão com o banco caiu")])

    reply = _responder(_pergunta(conversa), catalogo, provider=provider, executor=executor)

    assert len(provider.plan_requests) == 1
    assert reply.decision == AIReply.Decision.FAILED
    assert reply.rule == "banco_indisponivel"
    assert reply.reply_text == canned.BANCO_INDISPONIVEL


def test_banco_fora_do_ar_nao_vira_lacuna_do_catalogo(conversa, catalogo):
    executor = FakeQueryExecutor([QueryUnavailable("conexão recusada")])

    _responder(_pergunta(conversa), catalogo, provider=ScriptedAIProvider([plano()]), executor=executor)

    assert CatalogGap.objects.count() == 0


def test_aviso_nao_mostra_detalhe_tecnico_da_conexao():
    """Host e porta do banco não são assunto de quem perguntou."""
    assert "127.0.0.1" not in canned.BANCO_INDISPONIVEL
    assert "port" not in canned.BANCO_INDISPONIVEL


def test_executor_traduz_conexao_recusada(monkeypatch):
    def recusa(**_):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(psycopg2, "connect", recusa)
    executor = PostgresReadOnlyExecutor(dsn="postgresql://u:p@127.0.0.1:1/x")

    with pytest.raises(QueryUnavailable):
        executor.run("SELECT 1")
