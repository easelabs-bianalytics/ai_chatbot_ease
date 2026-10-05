"""Várias consultas numa resposta (ADR-0026, ponto B).

Incidente (Paulo, 2026-09-23): "a evolução prescritiva e o ranking das
especialidades que mais prescreveram" virou uma consulta só, com `UNION ALL`
e colunas nulas, meio vazia de cada lado. Agora cada entrega tem a sua
consulta, e cada uma aparece na resposta.
"""

import pytest

from ai_orchestrator.models import AICall, AIReply
from datasource.executors.base import QueryUnavailable
from datasource.executors.fake import FakeQueryExecutor, make_result
from tests.fakes.providers import ScriptedAIProvider, plano, resposta
from tests.unit.test_orchestrator import _pergunta, _responder, catalogo, conversa  # noqa: F401

pytestmark = pytest.mark.django_db

EVOLUCAO = make_result(("competencia", "px"), [("2026-01-01", 4327.0), ("2026-02-01", 4821.0)])
RANKING = make_result(("especialidade", "px", "posicao"), [("NEUROLOGIA", 11907.0, 1), ("PSIQUIATRIA", 10351.0, 2)])
SQL_EVOLUCAO = "SELECT data AS competencia, SUM(und) AS px FROM cddd.vendas_consolidado GROUP BY 1"
SQL_RANKING = "SELECT canal AS especialidade, SUM(und) AS px FROM cddd.vendas_consolidado GROUP BY 1"
PERGUNTA = "Mostre a evolução prescritiva e o ranking das especialidades que mais prescreveram"


def _plano_de_entregas(*consultas, **campos):
    return plano("", consultas=tuple(consultas), entendimento="PX mês a mês e ranking por especialidade", **campos)


def _entrega(titulo, sql, referencia="A01"):
    return {"titulo": titulo, "sql": sql, "reference_query_id": referencia}


def test_cada_entrega_tem_a_sua_consulta_e_aparece_na_resposta(conversa, catalogo):
    provider = ScriptedAIProvider(
        [_plano_de_entregas(_entrega("Evolução mensal", SQL_EVOLUCAO), _entrega("Ranking", SQL_RANKING, "A06"))],
        # A redação só apontou a primeira consulta: a segunda entra sozinha.
        [resposta("Neurologia lidera com 11907 PX.", blocos=(
            {"tipo": "texto", "texto": "Neurologia lidera com 11907 PX."},
            {"tipo": "grafico", "consulta": 0,
             "grafico": {"tipo": "linha", "x": "competencia", "series": ["px"], "titulo": ""}},
        ))],
    )
    executor = FakeQueryExecutor([EVOLUCAO, RANKING])

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider, executor=executor)

    assert reply.decision == AIReply.Decision.ANSWERED
    assert len(executor.executed) == 2
    pedido = provider.answer_requests[0]
    assert pedido.entregas is True
    assert [c["titulo"] for c in pedido.consultas] == ["Evolução mensal", "Ranking"]
    assert pedido.entendimento == "PX mês a mês e ranking por especialidade"
    blocos = reply.raw_response["blocos"]
    assert [b["tipo"] for b in blocos] == ["texto", "grafico", "tabela"]
    assert blocos[2]["consulta"] == 1 and set(reply.raw_response["dados_blocos"]) == {"0", "1"}
    assert [e["titulo"] for e in reply.raw_response["entregas"]] == ["Evolução mensal", "Ranking"]
    assert reply.query_runs.count() == 2


def test_consulta_de_entrega_recusada_ganha_uma_correcao(conversa, catalogo):
    provider = ScriptedAIProvider(
        [_plano_de_entregas(_entrega("Evolução mensal", SQL_EVOLUCAO), _entrega("Ranking", "DELETE FROM x")),
         plano(SQL_RANKING)],
        [resposta("Neurologia lidera com 11907 PX.")],
    )

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([EVOLUCAO, RANKING]))

    assert "«Ranking»" in provider.plan_requests[1].error_note
    assert reply.calls.filter(stage=AICall.Stage.FIX).count() == 1
    assert len(provider.answer_requests[0].consultas) == 2


def test_entrega_sem_linhas_e_dita_e_as_outras_seguem(conversa, catalogo):
    provider = ScriptedAIProvider(
        [_plano_de_entregas(_entrega("Evolução mensal", SQL_EVOLUCAO), _entrega("Ranking", SQL_RANKING))],
        [resposta("Foram 4821 PX em fev/2026.")],
    )
    vazio = make_result(("especialidade", "px"), [])

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([EVOLUCAO, vazio]))

    pedido = provider.answer_requests[0]
    assert len(pedido.consultas) == 1
    assert "«Ranking» voltou sem linhas" in pedido.pedido_nao_atendido
    assert reply.decision == AIReply.Decision.ANSWERED


def test_banco_fora_do_ar_para_as_entregas(conversa, catalogo):
    provider = ScriptedAIProvider(
        [_plano_de_entregas(_entrega("Evolução mensal", SQL_EVOLUCAO), _entrega("Ranking", SQL_RANKING))], [],
    )

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider,
                       executor=FakeQueryExecutor([QueryUnavailable("sem conexão")]))

    assert reply.rule == "banco_indisponivel"
    assert provider.answer_requests == []


def test_uma_entrega_so_segue_o_caminho_comum(conversa, catalogo):
    """Uma consulta em `consultas` é pergunta comum: gráfico, planilha e
    autocrítica continuam valendo."""
    provider = ScriptedAIProvider([_plano_de_entregas(_entrega("Evolução", SQL_EVOLUCAO))],
                                  [resposta("Foram 4821 PX em fev/2026.")])

    reply = _responder(_pergunta(conversa, "evolução de PX"), catalogo, provider=provider,
                       executor=FakeQueryExecutor([EVOLUCAO]))

    assert provider.answer_requests[0].sql == SQL_EVOLUCAO
    assert provider.answer_requests[0].entregas is False
    assert "entregas" not in reply.raw_response


@pytest.mark.parametrize("texto", [
    "Puxa os médicos da Área Médica e do Email MKT. Quero um excel exportado, um por aba",
    "E cadê o Excel??",
    "exporta a evolução e o ranking",
])
def test_pedido_de_excel_pela_palavra_fica_no_registro_e_vai_a_redacao(conversa, catalogo, texto):
    """Conversa 71 (2026-10-05): o plano veio sem `excel` nas duas perguntas
    ("quero um excel exportado, um por aba" e "E cadê o Excel??"), o
    registro não guardava o pedido nas entregas, e saiu tabela sem arquivo
    — a segunda resposta ainda disse que "o arquivo não foi anexado"."""
    from messaging.planilha_da_resposta import EXPORT_MAX_ROWS

    provider = ScriptedAIProvider(
        [_plano_de_entregas(_entrega("Evolução mensal", SQL_EVOLUCAO), _entrega("Ranking", SQL_RANKING))],
        [resposta("Neurologia lidera com 11907 PX.")],
    )
    executor = FakeQueryExecutor([EVOLUCAO, RANKING])

    reply = _responder(_pergunta(conversa, texto), catalogo, provider=provider, executor=executor)

    assert reply.raw_response["excel"] is True
    assert provider.answer_requests[0].excel is True
    assert executor.max_rows == [EXPORT_MAX_ROWS, EXPORT_MAX_ROWS]


def test_sem_pedido_de_arquivo_as_entregas_seguem_no_limite_da_tela(conversa, catalogo):
    provider = ScriptedAIProvider(
        [_plano_de_entregas(_entrega("Evolução mensal", SQL_EVOLUCAO), _entrega("Ranking", SQL_RANKING))],
        [resposta("Neurologia lidera com 11907 PX.")],
    )
    executor = FakeQueryExecutor([EVOLUCAO, RANKING])

    reply = _responder(_pergunta(conversa, PERGUNTA), catalogo, provider=provider, executor=executor)

    assert reply.raw_response["excel"] is False
    assert executor.max_rows == [catalogo.max_rows, catalogo.max_rows]


@pytest.mark.parametrize("texto, anexo, esperado", [
    ("quero em excel", "", True),
    ("me manda em planilha", "", True),
    ("preencha a planilha com o sell out de agosto", "planilha", False),
    ("preencha e me devolva em excel", "planilha", True),
    ("qual o PX de agosto?", "", False),
])
def test_quando_a_mensagem_pede_arquivo(texto, anexo, esperado):
    """"Planilha" com anexo é a planilha DA pessoa (ADR-0024/0031), com o
    caminho próprio; sem anexo, é pedido de arquivo."""
    from types import SimpleNamespace

    from ai_orchestrator.orchestrator import _pediu_planilha

    assert _pediu_planilha(SimpleNamespace(content=texto, anexo_tipo=anexo)) is esperado
