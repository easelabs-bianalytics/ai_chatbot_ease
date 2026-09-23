"""Pipeline do orquestrador, ramo a ramo, com IA e banco programados.

Cada teste aqui fixa uma decisão de produto: o que o usuário recebe quando a
IA não sabe, quando a consulta é recusada, quando o banco falha e quando a
resposta cita número que não existe.
"""

import json

import pytest

from ai_orchestrator.models import AICall, AIReply, CatalogGap
from ai_orchestrator.orchestrator import handle_message
from ai_orchestrator.providers.base import AIProviderError, Plan
from ai_orchestrator.providers.fake import FailingAIProvider
from catalog.loader import load_catalog
from conversations.models import Conversation
from datasource.executors.base import QueryExecutionError, QueryTimeout
from datasource.executors.fake import FakeQueryExecutor, make_result
from datasource.models import QueryRun
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta

pytestmark = pytest.mark.django_db

RESULTADO = make_result(("sku", "unidades"), [("259434", 47.0)])


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


@pytest.fixture
def conversa(django_user_model):
    user = django_user_model.objects.create_user("ana", password="x")
    return Conversation.objects.create(user=user)


def _pergunta(conversa, texto="unidades de Extrato em agosto de 2026", client_id="c-1"):
    return Message.objects.create(
        conversation=conversa,
        direction=Message.Direction.INBOUND,
        content=texto,
        client_message_id=client_id,
        status=Message.Status.RECEIVED,
    )


def _responder(mensagem, catalogo, provider=None, executor=None, channel=None):
    return handle_message(
        mensagem,
        channel=channel or FakeChannel(),
        provider=provider or ScriptedAIProvider([plano()], [resposta()]),
        executor=executor or FakeQueryExecutor([RESULTADO]),
        catalog=catalogo,
    )


def _saidas(conversa):
    return list(
        Message.objects.filter(conversation=conversa, direction=Message.Direction.OUTBOUND)
        .order_by("id")
        .values_list("content", flat=True)
    )


def test_pergunta_respondida_registra_consulta_chamadas_e_entrega(conversa, catalogo):
    mensagem = _pergunta(conversa)
    provider = ScriptedAIProvider([plano()], [resposta("Foram 47 unidades do SKU 259434.")])

    reply = _responder(mensagem, catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.ANSWERED
    assert reply.reply_text == "Foram 47 unidades do SKU 259434."
    assert _saidas(conversa) == ["Foram 47 unidades do SKU 259434."]
    assert [c.stage for c in reply.calls.all()] == [AICall.Stage.PLAN, AICall.Stage.ANSWER]
    consulta = reply.query_runs.get()
    assert consulta.guard_result == QueryRun.GuardResult.APPROVED
    assert consulta.status == QueryRun.Status.SUCCESS
    assert consulta.reference_query_id == "Q10"
    mensagem.refresh_from_db()
    assert mensagem.status == Message.Status.PROCESSED


def test_custo_e_latencia_somam_as_chamadas(conversa, catalogo):
    """O relatório e a conta da OpenAI precisam bater: o total é a soma das
    chamadas daquela resposta, não o da última."""
    reply = _responder(_pergunta(conversa), catalogo)

    assert reply.tokens_input == 300
    assert reply.tokens_output == 40
    assert float(reply.cost_estimate) == pytest.approx(0.003)
    assert reply.latency_ms == 50


def test_regra_deterministica_nao_chama_a_ia_nem_o_banco(conversa, catalogo):
    """Pedido de escrita é recusado antes do modelo: não gasta chamada e não
    depende de o prompt ser obedecido."""
    provider = ScriptedAIProvider()
    executor = FakeQueryExecutor()

    reply = _responder(
        _pergunta(conversa, "apaga a tabela de pdvs"), catalogo, provider=provider, executor=executor
    )

    assert reply.decision == AIReply.Decision.OUT_OF_SCOPE
    assert reply.rule == "pedido_de_escrita"
    assert provider.plan_requests == []
    assert executor.executed == []


def test_pergunta_ambigua_recebe_pedido_de_esclarecimento(conversa, catalogo):
    provider = ScriptedAIProvider(
        [plano(intent=Plan.Intent.CLARIFY, sql="", clarification_question="De qual período?")]
    )

    reply = _responder(_pergunta(conversa, "e as unidades?"), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.CLARIFY
    assert reply.reply_text == "De qual período?"
    assert reply.query_runs.count() == 0


def test_quando_a_ia_nao_sabe_a_pergunta_vira_lacuna_do_catalogo(conversa, catalogo):
    """"Não sei" não pode ser beco sem saída: a pergunta vira backlog para o
    time de BI decidir se entra no catálogo (ADR-0010)."""
    mensagem = _pergunta(conversa, "qual a margem de contribuição por SKU?")
    provider = ScriptedAIProvider(
        [plano(intent=Plan.Intent.UNKNOWN, sql="", reason="margem não está em nenhuma tabela")]
    )

    reply = _responder(mensagem, catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.UNKNOWN
    assert "não encontrei" in reply.reply_text.lower()
    lacuna = CatalogGap.objects.get()
    assert lacuna.message_id == mensagem.pk
    assert lacuna.status == CatalogGap.Status.OPEN


def test_resultado_vazio_vira_consulta_de_verificacao(conversa, catalogo):
    """"Nenhuma linha" quase nunca é "não houve venda": em geral o nome não
    casou com o cadastro ou o período não tem carga (2026-09-18). Antes de
    responder, uma segunda consulta procura o motivo."""
    verificacao = "SELECT nome, data_demissao FROM cddd.dim_ct WHERE nome ILIKE '%RICARDO%'"
    provider = ScriptedAIProvider(
        [plano(), plano(sql=verificacao, reference_query_id="E04")],
        [resposta("O Ricardo Reis saiu em 18/05/2026, então não há ago/2026 para comparar.")],
    )
    executor = FakeQueryExecutor([
        make_result(("representante", "unidades"), []),
        make_result(("nome", "data_demissao"), [("Ricardo Reis", "2026-05-18")]),
    ])

    reply = _responder(
        _pergunta(conversa, "compare o sell out do Ricardo Reis com o do Hermes em ago/26"),
        catalogo, provider=provider, executor=executor,
    )

    assert reply.decision == AIReply.Decision.EMPTY_RESULT
    assert "18/05/2026" in reply.reply_text
    assert provider.answer_requests[0].verification is True
    assert len(executor.executed) == 2
    # a segunda consulta fica registrada como qualquer outra
    assert [c.status for c in reply.query_runs.all()] == [QueryRun.Status.SUCCESS] * 2


def test_verificacao_tambem_vazia_volta_ao_aviso_de_sempre(conversa, catalogo):
    """Sem diagnóstico não há o que explicar: o usuário recebe o aviso curto,
    e não uma invenção sobre o motivo."""
    provider = ScriptedAIProvider([plano(), plano(sql="SELECT 1 FROM cddd.pdvs")], [])
    executor = FakeQueryExecutor([
        make_result(("sku", "unidades"), []),
        make_result(("nome",), []),
    ])

    reply = _responder(_pergunta(conversa), catalogo, provider=provider, executor=executor)

    assert reply.decision == AIReply.Decision.EMPTY_RESULT
    assert reply.rule == "resultado_vazio_sem_diagnostico"
    assert "não retornou nenhuma linha" in reply.reply_text
    assert provider.answer_requests == []


def test_verificacao_que_a_ia_desiste_usa_o_texto_dela(conversa, catalogo):
    """Se a IA já sabe dizer o que faltou, o texto dela é melhor que o fixo."""
    provider = ScriptedAIProvider(
        [plano(), plano(intent=Plan.Intent.UNKNOWN, sql="",
                        user_message="Não encontrei esse representante na força de vendas.")],
        [],
    )
    executor = FakeQueryExecutor([make_result(("sku", "unidades"), [])])

    reply = _responder(_pergunta(conversa), catalogo, provider=provider, executor=executor)

    assert reply.decision == AIReply.Decision.EMPTY_RESULT
    assert reply.reply_text == "Não encontrei esse representante na força de vendas."
    assert len(executor.executed) == 1


def test_verificacao_nao_vira_grafico(conversa, catalogo):
    """O resultado da verificação é cadastral: desenhá-lo daria ao
    diagnóstico a aparência da resposta que não existe."""
    provider = ScriptedAIProvider(
        [plano(), plano(sql="SELECT mes, und FROM cddd.vendas_consolidado")],
        [resposta("O último mês com movimento é jul/2026.",
                  chart={"tipo": "linha", "x": "mes", "series": ["und"], "titulo": ""})],
    )
    executor = FakeQueryExecutor([
        make_result(("mes", "und"), []),
        make_result(("mes", "und"), [("2026-06", 10), ("2026-07", 12)]),
    ])

    reply = _responder(_pergunta(conversa), catalogo, provider=provider, executor=executor)

    assert "grafico" not in reply.raw_response


def test_consulta_recusada_pelo_validador_e_corrigida_uma_vez(conversa, catalogo):
    """A IA erra o schema, o validador explica, ela conserta. As duas
    tentativas ficam registradas — a reprovada é a que interessa depois."""
    provider = ScriptedAIProvider(
        [
            plano(sql="SELECT * FROM financeiro.folha"),
            plano(sql="SELECT und FROM cddd.vendas_consolidado"),
        ],
        [resposta("Foram 47 unidades.")],
    )

    reply = _responder(_pergunta(conversa), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.ANSWERED
    tentativas = list(reply.query_runs.order_by("attempt"))
    assert [t.guard_result for t in tentativas] == [
        QueryRun.GuardResult.REJECTED,
        QueryRun.GuardResult.APPROVED,
    ]
    assert "não está liberado" in tentativas[0].guard_reason
    assert "não está liberado" in provider.plan_requests[1].error_note
    assert [c.stage for c in reply.calls.all()] == [
        AICall.Stage.PLAN,
        AICall.Stage.FIX,
        AICall.Stage.ANSWER,
    ]


def test_consulta_recusada_duas_vezes_para_de_tentar(conversa, catalogo):
    """Sem esse limite, uma pergunta difícil viraria um laço de chamadas
    pagas. Duas tentativas e o sistema assume que não vai sair."""
    mensagem = _pergunta(conversa)
    provider = ScriptedAIProvider(
        [plano(sql="DELETE FROM cddd.pdvs"), plano(sql="DROP TABLE cddd.pdvs")]
    )

    reply = _responder(mensagem, catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.FAILED
    assert reply.rule == "consulta_falhou_duas_vezes"
    assert reply.query_runs.count() == 2
    assert CatalogGap.objects.count() == 1
    mensagem.refresh_from_db()
    assert mensagem.status == Message.Status.FAILED
    assert _saidas(conversa) == [reply.reply_text]


def test_erro_do_banco_volta_para_a_ia_e_a_segunda_tentativa_funciona(conversa, catalogo):
    """Coluna inexistente é o erro mais comum de SQL gerado. A mensagem do
    Postgres é o que diz à IA o que corrigir (ADR-0014)."""
    provider = ScriptedAIProvider(
        [plano(sql="SELECT unidade FROM cddd.vendas_consolidado"), plano()],
        [resposta("Foram 47 unidades.")],
    )
    executor = FakeQueryExecutor(
        [QueryExecutionError('column "unidade" does not exist'), RESULTADO]
    )

    reply = _responder(_pergunta(conversa), catalogo, provider=provider, executor=executor)

    assert reply.decision == AIReply.Decision.ANSWERED
    tentativas = list(reply.query_runs.order_by("attempt"))
    assert tentativas[0].status == QueryRun.Status.ERROR
    assert "unidade" in tentativas[0].error
    assert "unidade" in provider.plan_requests[1].error_note


def test_timeout_do_banco_fica_registrado_como_timeout(conversa, catalogo):
    """Distinguir timeout de erro importa: timeout é consulta pesada demais,
    e a saída é filtrar período ou agregar mais."""
    provider = ScriptedAIProvider([plano(), plano()])
    executor = FakeQueryExecutor([QueryTimeout("passou de 15000 ms"), QueryTimeout("de novo")])

    reply = _responder(_pergunta(conversa), catalogo, provider=provider, executor=executor)

    assert reply.decision == AIReply.Decision.FAILED
    assert [t.status for t in reply.query_runs.order_by("attempt")] == [
        QueryRun.Status.TIMEOUT,
        QueryRun.Status.TIMEOUT,
    ]


def test_ia_que_desiste_na_correcao_vira_nao_sei(conversa, catalogo):
    """Se na segunda tentativa a IA diz que não sabe, forçar uma terceira só
    gastaria tokens."""
    provider = ScriptedAIProvider(
        [
            plano(sql="SELECT * FROM financeiro.folha"),
            plano(intent=Plan.Intent.UNKNOWN, sql="", reason="não sei onde está esse dado"),
        ]
    )

    reply = _responder(_pergunta(conversa), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.UNKNOWN
    assert CatalogGap.objects.count() == 1


def test_numero_sem_suporte_faz_a_ia_reescrever_uma_vez(conversa, catalogo):
    """O modelo somou por conta própria. A checagem pega, ele reescreve com o
    motivo, e o usuário recebe a versão ancorada (ADR-0010)."""
    provider = ScriptedAIProvider(
        [plano()],
        [resposta("Foram 52 unidades no total."), resposta("Foram 47 unidades do SKU 259434.")],
    )

    reply = _responder(_pergunta(conversa), catalogo, provider=provider)

    assert reply.reply_text == "Foram 47 unidades do SKU 259434."
    assert _saidas(conversa) == ["Foram 47 unidades do SKU 259434."]
    assert "52" in provider.answer_requests[1].revision_note
    assert reply.raw_response["rascunho_reprovado"] == ["Foram 52 unidades no total."]
    assert [c.stage for c in reply.calls.all()][-1] == AICall.Stage.REWRITE


def test_numero_sem_suporte_duas_vezes_entrega_a_tabela_sem_narrativa(conversa, catalogo):
    """O dado continua chegando ao usuário; o que não sai é a frase inventada.
    Silêncio seria pior: o número existe e está correto no resultado."""
    provider = ScriptedAIProvider(
        [plano()], [resposta("Foram 52 unidades."), resposta("Na verdade foram 63 unidades.")]
    )

    reply = _responder(_pergunta(conversa), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.ANSWERED
    assert reply.rule == "resposta_sem_narrativa"
    assert "sku | unidades" in reply.reply_text
    assert "259434" in reply.reply_text
    assert reply.raw_response["rascunho_reprovado"] == [
        "Foram 52 unidades.",
        "Na verdade foram 63 unidades.",
    ]


def test_resultado_truncado_avisa_no_texto(conversa, catalogo):
    """Sem o aviso, uma lista cortada no limite passaria por lista completa."""
    executor = FakeQueryExecutor(
        [make_result(("sku", "unidades"), [("259434", 47.0)], truncated=True)]
    )

    reply = _responder(
        _pergunta(conversa),
        catalogo,
        provider=ScriptedAIProvider([plano()], [resposta("Foram 47 unidades.")]),
        executor=executor,
    )

    assert "cortado no limite" in reply.reply_text


def test_falha_do_provedor_de_ia_vira_aviso_legivel(conversa, catalogo):
    """A exceção não pode derrubar a tarefa: o usuário fica sem resposta e sem
    registro do que aconteceu."""
    mensagem = _pergunta(conversa)

    reply = _responder(mensagem, catalogo, provider=FailingAIProvider())

    assert reply.decision == AIReply.Decision.FAILED
    assert reply.rule == "falha_da_ia"
    assert "problema técnico" in reply.reply_text
    assert reply.raw_response["erro"]
    mensagem.refresh_from_db()
    assert mensagem.status == Message.Status.FAILED
    assert _saidas(conversa) == [reply.reply_text]


def test_processar_a_mesma_pergunta_de_novo_nao_gera_segunda_resposta(conversa, catalogo):
    """A tarefa Celery pode ser reentregue depois de o worker cair (ADR-0003).
    Refazer custaria duas chamadas de modelo e uma consulta para dizer o
    mesmo — ou, pior, algo diferente."""
    mensagem = _pergunta(conversa)
    provider = ScriptedAIProvider([plano()], [resposta("Foram 47 unidades.")])

    primeira = _responder(mensagem, catalogo, provider=provider)
    segunda = _responder(mensagem, catalogo, provider=provider)

    assert segunda.pk == primeira.pk
    assert len(provider.plan_requests) == 1
    assert len(_saidas(conversa)) == 1
    assert AIReply.objects.count() == 1


def test_historico_da_conversa_vai_para_a_ia(conversa, catalogo):
    """"E em julho?" só faz sentido com a pergunta anterior junto."""
    provider = ScriptedAIProvider(
        [plano(), plano()], [resposta("Foram 47 unidades."), resposta("Foram 47 unidades em julho.")]
    )

    _responder(_pergunta(conversa), catalogo, provider=provider)
    _responder(_pergunta(conversa, "e em julho?", client_id="c-2"), catalogo, provider=provider)

    historico = provider.plan_requests[1].history
    assert [h.direction for h in historico] == ["in", "out"]
    assert historico[0].text == "unidades de Extrato em agosto de 2026"


def test_pergunta_seguinte_nao_enxerga_conversa_de_outro_assunto(conversa, catalogo, django_user_model):
    """O histórico é da conversa, não do usuário: cada thread é um assunto, e
    misturar faria "e em julho?" seguir a pergunta errada."""
    outra = Conversation.objects.create(user=conversa.user)
    provider = ScriptedAIProvider([plano(), plano()], [resposta("Foram 47 unidades.")] * 2)

    _responder(_pergunta(conversa, "unidades de agosto"), catalogo, provider=provider)
    _responder(_pergunta(outra, "e em julho?", client_id="c-9"), catalogo, provider=provider)

    assert provider.plan_requests[1].history == ()


def test_tabela_inexistente_vira_informacao_indisponivel_sem_nova_tentativa(conversa, catalogo):
    """Metas: o schema remuneracao_fv ainda não existe. A regra do time de BI é
    não trocar por outra tabela nem estimar — responder que a informação não
    está disponível. Uma segunda tentativa só convidaria a IA a improvisar."""
    from datasource.executors.base import QueryObjectMissing

    mensagem = _pergunta(conversa, "os representantes bateram a meta em agosto de 2026?")
    provider = ScriptedAIProvider([plano(sql="SELECT mes FROM remuneracao_fv.fato_remuneracao")])
    executor = FakeQueryExecutor(
        [QueryObjectMissing('relation "remuneracao_fv.fato_remuneracao" does not exist')]
    )

    reply = _responder(mensagem, catalogo, provider=provider, executor=executor)

    assert reply.decision == AIReply.Decision.UNKNOWN
    assert reply.rule == "objeto_inexistente_no_banco"
    assert "ainda não está disponível" in reply.reply_text
    assert len(provider.plan_requests) == 1
    assert CatalogGap.objects.get().message_id == mensagem.pk


def test_fora_de_escopo_usa_a_orientacao_escrita_pela_ia(conversa, catalogo):
    """Forecast vai para o app de Forecast de Reposição. O texto fixo de "não
    altero dados" responderia outra coisa."""
    orientacao = "Projeções ficam no app de Forecast de Reposição. Posso mostrar o estoque de hoje?"
    provider = ScriptedAIProvider(
        [plano(intent=Plan.Intent.OUT_OF_SCOPE, sql="", user_message=orientacao)]
    )

    reply = _responder(_pergunta(conversa, "qual a projeção de sell out da Raia?"), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.OUT_OF_SCOPE
    assert reply.reply_text == orientacao


def test_mensagem_sem_dado_com_numero_vira_texto_padrao(conversa, catalogo):
    """Sem consulta não há número de onde tirar: uma meta "estimada" no texto
    de "não disponível" seria exatamente a alucinação que o produto proíbe."""
    provider = ScriptedAIProvider(
        [plano(intent=Plan.Intent.UNKNOWN, sql="", user_message="A meta deve ser uns 50 mil.")]
    )

    reply = _responder(_pergunta(conversa, "qual a meta do Hermes?"), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.UNKNOWN
    assert "50" not in reply.reply_text
    assert CatalogGap.objects.count() == 1


def test_ia_pode_pedir_o_documento_inteiro_quando_o_recorte_nao_basta(conversa, catalogo):
    """O contexto vai recortado por tema (ADR-0015). Sem esta saída, uma
    pergunta que cruza áreas faria a IA inventar a regra que faltou."""
    provider = ScriptedAIProvider(
        [
            plano(intent=Plan.Intent.UNKNOWN, sql="", reason="PRECISO DA SEÇÃO: sell_out"),
            plano(sql="SELECT und FROM cddd.vendas_consolidado"),
        ],
        [resposta("Foram 47 unidades.")],
    )

    reply = _responder(_pergunta(conversa, "prescrição e venda no território do Hermes"),
                       catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.ANSWERED
    assert provider.plan_requests[1].full_context is True
    assert [c.stage for c in reply.calls.all()] == [
        AICall.Stage.PLAN, AICall.Stage.FIX, AICall.Stage.ANSWER
    ]


def test_teto_de_gasto_atingido_nao_chama_o_modelo(conversa, catalogo, monkeypatch):
    """O custo por pergunta é estimativa até rodar de verdade; o teto é o que
    impede a estimativa errada de virar fatura (O-14)."""
    from ai_orchestrator import budget

    monkeypatch.setenv(budget.VARIAVEL, "0.01")
    provider = ScriptedAIProvider([plano()], [resposta()])
    anterior = _pergunta(conversa, "quanto vendemos em julho?", client_id="c-teto")
    AIReply.objects.create(
        message=anterior, decision=AIReply.Decision.ANSWERED, cost_estimate="0.02"
    )

    reply = _responder(_pergunta(conversa, "e em agosto?", client_id="c-teto-2"),
                       catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.FAILED
    assert reply.rule == "teto_de_custo_do_mes"
    assert "limite de uso" in reply.reply_text
    assert provider.plan_requests == []


def test_sem_credito_na_ia_vira_aviso_discreto(conversa, catalogo):
    """Com o limite da OpenAI atingido, quem perguntou não fez nada de
    errado: recebe um aviso para falar com o time de BI, não um erro."""
    from ai_orchestrator.providers.base import AIQuotaExceeded

    provider = ScriptedAIProvider([AIQuotaExceeded("insufficient_quota")])

    reply = _responder(_pergunta(conversa, "vendas de agosto de 2026"), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.FAILED
    assert reply.rule == "sem_creditos_na_ia"
    assert "sem créditos" in reply.reply_text
    assert "BI & Analytics" in reply.reply_text


def test_conversa_responde_sem_consultar(conversa, catalogo):
    """"Quem é você?" não é pergunta de dado: responder com o selo "dado não
    disponível" confundia quem só queria conversar."""
    provider = ScriptedAIProvider(
        [plano(intent=Plan.Intent.CONVERSATION, sql="", user_message="Sou o Jarvis, copiloto de dados da Ease Labs.")]
    )
    executor = FakeQueryExecutor()

    reply = _responder(_pergunta(conversa, "quem é você?"), catalogo, provider=provider, executor=executor)

    assert reply.decision == AIReply.Decision.CONVERSATION
    assert reply.reply_text == "Sou o Jarvis, copiloto de dados da Ease Labs."
    assert executor.executed == []
    assert CatalogGap.objects.count() == 0
    assert [c.stage for c in reply.calls.all()] == [AICall.Stage.PLAN]


def test_conversa_pode_citar_numero_que_ja_esta_na_conversa(conversa, catalogo):
    """Interpretar a queda de julho usa os números que a consulta anterior
    trouxe — e só eles."""
    Message.objects.create(
        conversation=conversa, direction=Message.Direction.OUTBOUND,
        content="Foram 761 unidades em jul/2026 e 777 em ago/2026.", client_message_id="out-1",
    )
    texto = "A variação entre 761 e 777 é pequena; uma hipótese é o estoque nos CDs."
    provider = ScriptedAIProvider([plano(intent=Plan.Intent.CONVERSATION, sql="", user_message=texto)])

    reply = _responder(_pergunta(conversa, "o que explica isso?", client_id="c-2"), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.CONVERSATION
    assert reply.reply_text == texto


def test_conversa_com_numero_novo_vira_pedido_de_consulta(conversa, catalogo):
    """Sem consulta não há de onde tirar número: a conversa não pode ser a
    porta dos fundos para a alucinação que o produto proíbe (ADR-0010)."""
    provider = ScriptedAIProvider(
        [plano(intent=Plan.Intent.CONVERSATION, sql="", user_message="A queda foi de uns 12% por causa da ruptura.")]
    )

    reply = _responder(_pergunta(conversa, "por que o sell out caiu?"), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.CONVERSATION
    assert reply.rule == "conversa_com_numero_sem_fonte"
    assert "12" not in reply.reply_text
    assert "sem fonte" in reply.reply_text


def test_interrogacao_no_meio_da_conversa_vai_para_a_ia(conversa, catalogo):
    """Em 2026-09-23 o Jarvis prometeu um gráfico, não fez, e ao "?" do Paulo
    respondeu "não consegui entender a pergunta". No meio de uma conversa,
    "?" é cobrança do que faltou: quem lê é a IA, com o histórico."""
    Message.objects.create(
        conversation=conversa, direction=Message.Direction.OUTBOUND,
        content="Vou ajustar para linhas por especialidade.", client_message_id="out-1",
    )
    provider = ScriptedAIProvider([plano()], [resposta("Pronto: linhas por especialidade, 47 PX.")])

    reply = _responder(_pergunta(conversa, "?", client_id="c-2"), catalogo, provider=provider)

    assert reply.rule != "mensagem_sem_pergunta"
    assert len(provider.plan_requests) == 1


def test_interrogacao_solta_numa_conversa_nova_continua_pedindo_a_pergunta(conversa, catalogo):
    provider = ScriptedAIProvider()

    reply = _responder(_pergunta(conversa, "?"), catalogo, provider=provider)

    assert reply.rule == "mensagem_sem_pergunta"
    assert provider.plan_requests == []


def test_historico_leva_a_consulta_da_resposta_anterior(conversa, catalogo):
    """"Faça um gráfico com esses dados" precisa saber quais dados: o
    planejador passa a ver a consulta que sustentou a resposta anterior."""
    provider = ScriptedAIProvider(
        [plano(reference_query_id="A06"), plano()],
        [resposta("Foram 47 PX."), resposta("Pronto, 47 PX no gráfico.")],
    )
    _responder(_pergunta(conversa, "PX por especialidade em 2026"), catalogo, provider=provider)

    _responder(_pergunta(conversa, "faça um gráfico com esses dados", client_id="c-2"), catalogo, provider=provider)

    anterior = [m for m in provider.plan_requests[1].history if m.direction == "out"][-1]
    assert "consulta (base A06)" in anterior.fonte
    assert "SELECT" in anterior.fonte.upper()


def test_pergunta_sobre_a_resposta_anterior_usa_a_consulta_dela(conversa, catalogo):
    """"Qual MAT você considerou?" se responde com o período que estava na
    consulta anterior, não no texto dela. Em 2026-09-23 a resposta certa foi
    trocada pelo texto de reserva duas vezes seguidas, e o Jarvis pareceu não
    entender uma pergunta sobre o que ele mesmo tinha acabado de responder."""
    mat = make_result(("cod_anomes", "unidades"), [("202509", 57146.0), ("202608", 67136.0)])
    texto = "Considerei o MAT de set/2025 a ago/2026: os 12 meses fechados até a última carga."
    provider = ScriptedAIProvider(
        [plano(), plano(intent=Plan.Intent.CONVERSATION, sql="", user_message=texto)],
        [resposta("No MAT, o mercado de Isolados chegou a 67.136 unidades no último mês.")],
    )
    _responder(
        _pergunta(conversa, "unidades de Isolado no MAT"),
        catalogo, provider=provider, executor=FakeQueryExecutor([mat]),
    )

    reply = _responder(
        _pergunta(conversa, "Qual foi o MAT que você considerou?", client_id="c-2"),
        catalogo, provider=provider,
    )

    assert reply.decision == AIReply.Decision.CONVERSATION
    assert reply.reply_text == texto


def test_pergunta_fica_marcada_como_em_consulta_so_quando_o_banco_e_chamado(conversa, catalogo):
    """A tela mostra "consultando os dados" a partir desse sinal; antes dele a
    IA ainda pode decidir responder sem consulta."""
    estados = []

    class Espiao(FakeQueryExecutor):
        def run(self, sql, max_rows=None):
            estados.append(Message.objects.get(pk=pergunta.pk).status)
            return super().run(sql, max_rows)

    pergunta = _pergunta(conversa)
    _responder(pergunta, catalogo, executor=Espiao([RESULTADO]))

    assert estados == [Message.Status.PROCESSING]
    pergunta.refresh_from_db()
    assert pergunta.status == Message.Status.PROCESSED


def test_assunto_fora_do_escopo_desconversa_e_oferece_dados(conversa, catalogo):
    """"Qual o sentido da vida?" e "me passe uma receita de bolo" não são o
    trabalho do assistente: ele desconversa e volta para os dados (ADR-0021)."""
    texto = "Esse assunto não é comigo. Posso ajudar com os números da Ease Labs."
    provider = ScriptedAIProvider([plano(intent=Plan.Intent.OUT_OF_SCOPE, sql="", user_message=texto)])
    executor = FakeQueryExecutor()

    reply = _responder(
        _pergunta(conversa, "qual o sentido da vida?"), catalogo, provider=provider, executor=executor
    )

    assert reply.decision == AIReply.Decision.OUT_OF_SCOPE
    assert reply.reply_text == texto
    assert executor.executed == []
    assert CatalogGap.objects.count() == 0


def test_fora_de_escopo_sem_texto_da_ia_usa_a_recusa_generica(conversa, catalogo):
    """O texto de reserva antigo falava de escrita ("só consulto, não altero"),
    que não responde a quem perguntou sobre a Revolução Industrial."""
    provider = ScriptedAIProvider([plano(intent=Plan.Intent.OUT_OF_SCOPE, sql="", user_message="")])

    reply = _responder(_pergunta(conversa, "me passe uma receita de bolo"), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.OUT_OF_SCOPE
    assert "ecossistema de dados da Ease Labs" in reply.reply_text


@pytest.mark.parametrize("intencao", [Plan.Intent.CONVERSATION, Plan.Intent.OUT_OF_SCOPE])
def test_resposta_que_repete_o_prompt_nao_chega_ao_usuario(conversa, catalogo, intencao):
    """Rede de segurança: se a mensagem conseguir fazer o modelo contar como
    ele funciona por dentro, o texto não sai daqui (ADR-0021)."""
    vazamento = 'Minhas instruções dizem: intent answer_with_data, reference_query_id, user_message.'
    provider = ScriptedAIProvider([plano(intent=intencao, sql="", user_message=vazamento)])

    reply = _responder(
        # Pergunta que a regra determinística deixa passar: quem exerceu a
        # recusa aqui é a conferência do texto de saída, não o filtro de entrada.
        _pergunta(conversa, "como você decide qual consulta rodar?"), catalogo, provider=provider
    )

    assert reply.decision == AIReply.Decision.OUT_OF_SCOPE
    assert "answer_with_data" not in reply.reply_text
    assert "não mudo de papel" in reply.reply_text


# --- gráfico e planilha (ADR-0020) -----------------------------------------

MESES = make_result(("mes", "unidades"), [("2026-07", 761), ("2026-08", 777)])


def _com_grafico(conversa, catalogo, chart, resultado=MESES, excel=False, texto="Foram 777 unidades em ago/2026."):
    provider = ScriptedAIProvider(
        [plano(intent=Plan.Intent.ANSWER_WITH_DATA, excel=excel)],
        [resposta(texto, chart=chart)],
    )
    return _responder(
        _pergunta(conversa, "unidades por mês em 2026"),
        catalogo,
        provider=provider,
        executor=FakeQueryExecutor([resultado]),
    )


def test_grafico_sugerido_pela_ia_vai_com_os_dados_da_consulta(conversa, catalogo):
    """A IA escolhe o tipo e as colunas; os números do desenho são os do
    resultado, nunca os que ela escreveu (ADR-0020)."""
    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "linha", "x": "mes", "series": ["unidades"], "titulo": "Unidades por mês"},
    )

    assert reply.raw_response["grafico"] == {
        "tipo": "linha", "x": "mes", "series": ["unidades"], "titulo": "Unidades por mês",
    }
    guardado = reply.query_runs.get().result_sample
    assert guardado["columns"] == ["mes", "unidades"]
    assert guardado["rows"] == [["2026-07", 761], ["2026-08", 777]]


PX_POR_ESPECIALIDADE = make_result(
    ("competencia", "especialidade", "px"),
    [("2026-01", "NEUROLOGIA", 900), ("2026-01", "PSIQUIATRIA", 700), ("2026-02", "NEUROLOGIA", 950)],
)


def test_grafico_por_categoria_empilhado(conversa, catalogo):
    """"Empilhe por especialidade" (2026-09-23): o resultado vem em formato
    longo, e cada especialidade vira uma série na tela."""
    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "barras", "x": "competencia", "series": ["px"], "grupo": "especialidade",
         "empilhado": True, "titulo": ""},
        resultado=PX_POR_ESPECIALIDADE, texto="Neurologia lidera com 950 PX em fev/2026.",
    )

    assert reply.raw_response["grafico"] == {
        "tipo": "barras", "x": "competencia", "series": ["px"], "titulo": "",
        "grupo": "especialidade", "empilhado": True,
    }


def test_grafico_em_vega_lite_vai_limpo_e_sem_dado(conversa, catalogo):
    """ADR-0026: "um gráfico de dispersão" sai em Vega-Lite. O que a IA pôs
    em `data` sai; quem põe os dados é a tela, com o resultado da consulta."""
    spec = {"data": {"values": [{"px": 1}]}, "mark": "point",
            "encoding": {"x": {"field": "competencia", "type": "temporal"}, "y": {"field": "px"}}}
    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "nenhum", "x": "", "series": [], "vega_lite": json.dumps(spec), "titulo": ""},
        resultado=PX_POR_ESPECIALIDADE, texto="Neurologia lidera com 950 PX em fev/2026.",
    )

    grafico = reply.raw_response["grafico"]
    assert grafico["tipo"] == "vega"
    assert "data" not in grafico["vega"]
    assert grafico["vega"]["mark"] == "point"


def test_vega_lite_invalido_cai_no_formato_simples(conversa, catalogo):
    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "barras", "x": "especialidade", "series": ["px"], "titulo": "",
         "vega_lite": json.dumps({"mark": "bar", "encoding": {"x": {"field": "rede"}}})},
        resultado=PX_POR_ESPECIALIDADE, texto="Neurologia lidera com 950 PX em fev/2026.",
    )

    assert reply.raw_response["grafico"]["tipo"] == "barras"


@pytest.mark.parametrize(
    "chart,esperado",
    [
        # a medida não é grupo: o eixo repete, e quem explica é a especialidade
        ({"tipo": "barras", "x": "competencia", "series": ["px"], "grupo": "px"}, {"grupo": "especialidade"}),
        # linha não empilha
        ({"tipo": "linha", "x": "competencia", "series": ["px"], "grupo": "especialidade", "empilhado": True},
         {"grupo": "especialidade"}),
        # pizza reparte uma medida pelas fatias: não tem grupo
        ({"tipo": "pizza", "x": "especialidade", "series": ["px"], "grupo": "competencia"}, {}),
    ],
)
def test_grupo_e_empilhado_so_onde_fazem_sentido(conversa, catalogo, chart, esperado):
    reply = _com_grafico(
        conversa, catalogo, {**chart, "titulo": ""},
        resultado=PX_POR_ESPECIALIDADE, texto="Neurologia lidera com 950 PX em fev/2026.",
    )

    grafico = reply.raw_response["grafico"]
    assert {k: grafico[k] for k in ("grupo", "empilhado") if k in grafico} == esperado


@pytest.mark.parametrize(
    "chart",
    [
        {"tipo": "linha", "x": "competencia", "series": ["unidades"], "titulo": ""},
        {"tipo": "linha", "x": "mes", "series": ["faturamento"], "titulo": ""},
        {"tipo": "radar", "x": "mes", "series": ["unidades"], "titulo": ""},
        {"tipo": "nenhum", "x": "", "series": [], "titulo": ""},
    ],
)
def test_grafico_com_coluna_ou_tipo_que_nao_existe_e_descartado(conversa, catalogo, chart):
    """Melhor nenhum gráfico do que um gráfico errado: quem confere as
    colunas contra o resultado é o orquestrador, não o modelo."""
    reply = _com_grafico(conversa, catalogo, chart)

    assert "grafico" not in reply.raw_response


def test_serie_que_nao_e_numero_nao_vira_grafico(conversa, catalogo):
    texto = make_result(("mes", "rede"), [("2026-07", "Pague Menos"), ("2026-08", "Drogasil")])

    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "barras", "x": "mes", "series": ["rede"], "titulo": ""},
        resultado=texto,
        texto="As redes do período estão na tabela.",
    )

    assert "grafico" not in reply.raw_response


def test_resultado_de_uma_linha_nao_vira_grafico(conversa, catalogo):
    """Uma barra sozinha não compara nada — a frase da resposta já diz."""
    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "barras", "x": "mes", "series": ["unidades"], "titulo": ""},
        resultado=make_result(("mes", "unidades"), [("2026-08", 777)]),
    )

    assert "grafico" not in reply.raw_response


def test_titulo_com_numero_que_nao_esta_no_resultado_e_removido(conversa, catalogo):
    """A ancoragem (ADR-0010) vale para o título do gráfico também."""
    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "linha", "x": "mes", "series": ["unidades"], "titulo": "Queda de 42% no semestre"},
    )

    assert reply.raw_response["grafico"]["titulo"] == ""


def test_pedido_de_planilha_nao_desenha_grafico(conversa, catalogo):
    """Quem pediu a lista em Excel quer a lista; o gráfico só ocuparia
    espaço acima do botão de download."""
    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "linha", "x": "mes", "series": ["unidades"], "titulo": "Unidades por mês"},
        excel=True,
    )

    assert reply.raw_response["excel"] is True
    assert "grafico" not in reply.raw_response


def test_sem_grafico_a_amostra_guardada_continua_pequena(conversa, catalogo):
    """Guardar o resultado inteiro só se justifica quando a tela vai
    desenhá-lo; fora disso a auditoria fica com a amostra de cinco linhas."""
    doze_meses = make_result(("mes", "unidades"), [(f"2026-{m:02d}", 700 + m) for m in range(1, 13)])

    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "nenhum", "x": "", "series": [], "titulo": ""},
        resultado=doze_meses,
        texto="A tabela traz o ano todo.",
    )

    assert len(reply.query_runs.get().result_sample["rows"]) == 5


def test_com_grafico_a_consulta_guarda_o_resultado_inteiro(conversa, catalogo):
    """A tela desenha com os números da consulta: com só cinco linhas
    guardadas, o gráfico do ano mostraria cinco meses."""
    doze_meses = make_result(("mes", "unidades"), [(f"2026-{m:02d}", 700 + m) for m in range(1, 13)])

    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "linha", "x": "mes", "series": ["unidades"], "titulo": "Unidades por mês"},
        resultado=doze_meses,
        texto="A tabela traz o ano todo.",
    )

    assert len(reply.query_runs.get().result_sample["rows"]) == 12


# --- continuações da conversa ------------------------------------------------


def _com_sugestoes(conversa, catalogo, sugestoes, pergunta="unidades de Extrato em agosto de 2026"):
    provider = ScriptedAIProvider(
        [plano()],
        [resposta("Foram 47 unidades.", followups=tuple(sugestoes))],
    )
    return _responder(_pergunta(conversa, pergunta), catalogo, provider=provider,
                      executor=FakeQueryExecutor([RESULTADO]))


def test_sugestoes_de_continuacao_chegam_na_resposta(conversa, catalogo):
    """A investigação raramente termina na primeira pergunta."""
    reply = _com_sugestoes(conversa, catalogo, ["E por rede?", "Compara com julho"])

    assert reply.raw_response["sugestoes"] == ["E por rede?", "Compara com julho"]


def test_no_maximo_tres_continuacoes(conversa, catalogo):
    reply = _com_sugestoes(conversa, catalogo, ["Uma?", "Duas?", "Três?", "Quatro?"])

    assert len(reply.raw_response["sugestoes"]) == 3


def test_descarta_continuacao_repetida_ou_longa_demais(conversa, catalogo):
    """Frase longa quebra o botão; repetida confunde."""
    reply = _com_sugestoes(conversa, catalogo, [
        "E por rede?", "e por rede", " ",
        "Quero que você me diga como ficou a evolução disso tudo mês a mês por rede e por PDV também",
    ])

    assert reply.raw_response["sugestoes"] == ["E por rede?"]


def test_descarta_continuacao_que_repete_a_pergunta(conversa, catalogo):
    """Sugerir o que o usuário acabou de perguntar faz parecer que a IA não
    entendeu."""
    reply = _com_sugestoes(conversa, catalogo, ["unidades de Extrato em agosto de 2026", "E por rede?"],
                           pergunta="unidades de Extrato em agosto de 2026")

    assert reply.raw_response["sugestoes"] == ["E por rede?"]


def test_sem_continuacao_o_campo_nem_aparece(conversa, catalogo):
    reply = _com_sugestoes(conversa, catalogo, [])

    assert "sugestoes" not in reply.raw_response


# --- ajuste do gráfico pela conversa -----------------------------------------


def _conversa_com_grafico(conversa, catalogo):
    """Deixa na conversa uma resposta com gráfico, como a tela mostraria."""
    provider = ScriptedAIProvider(
        [plano()],
        [resposta("Foram 47 unidades.",
                  chart={"tipo": "linha", "x": "sku", "series": ["unidades"], "titulo": "Unidades"})],
    )
    oito_skus = make_result(("sku", "unidades"),
                            [("259434", 47.0)] + [(f"2594{n}", float(n)) for n in range(35, 42)])
    reply = _responder(_pergunta(conversa, "unidades por SKU"), catalogo, provider=provider,
                       executor=FakeQueryExecutor([oito_skus]))
    assert reply.raw_response["grafico"]["tipo"] == "linha"
    return reply


def test_troca_o_tipo_do_grafico_sem_ia_e_sem_banco(conversa, catalogo):
    """Os números já estão na tela: refazer a consulta e pagar duas chamadas
    de modelo para trocar um tipo de gráfico seria desperdício."""
    _conversa_com_grafico(conversa, catalogo)
    provider = ScriptedAIProvider([], [])      # nenhuma chamada programada
    executor = FakeQueryExecutor()

    reply = _responder(_pergunta(conversa, "muda para barras", client_id="c-9"),
                       catalogo, provider=provider, executor=executor)

    assert reply.rule == "ajuste_de_grafico"
    assert reply.decision == AIReply.Decision.CONVERSATION
    assert reply.raw_response["grafico"]["tipo"] == "barras"
    assert reply.raw_response["grafico"]["x"] == "sku"        # o resto continua
    assert provider.plan_requests == [] and executor.executed == []
    assert reply.calls.count() == 0
    assert reply.cost_estimate in (None, 0)


def test_corte_pedido_entra_na_especificacao(conversa, catalogo):
    _conversa_com_grafico(conversa, catalogo)

    reply = _responder(_pergunta(conversa, "só os 5 primeiros", client_id="c-9"), catalogo,
                       provider=ScriptedAIProvider([], []), executor=FakeQueryExecutor())

    assert reply.raw_response["grafico"]["limite"] == 5
    assert "tabela acima continua" in reply.reply_text


def test_sem_grafico_na_conversa_o_pedido_segue_para_a_ia(conversa, catalogo):
    """"Muda para barras" numa conversa sem gráfico não é ajuste: é pergunta,
    e quem decide o que fazer com ela é o modelo."""
    provider = ScriptedAIProvider([plano(intent=Plan.Intent.CLARIFY, sql="",
                                         clarification_question="Barras de quê?")])

    reply = _responder(_pergunta(conversa, "muda para barras"), catalogo, provider=provider)

    assert reply.decision == AIReply.Decision.CLARIFY
    assert reply.rule == ""


# --- conversa 14 (2026-09-23): mês × categoria × PX --------------------------

PX_POR_CATEGORIA = make_result(
    ("competencia", "categoria", "px"),
    [("2026-01-01", 1, 520.0), ("2026-01-01", 3, 221.0), ("2026-02-01", 1, 617.0), ("2026-02-01", 3, 257.0)],
)


def test_eixo_repetido_ganha_o_grupo_mesmo_em_numero(conversa, catalogo):
    """Conversa 14: a redação pôs x=competencia e series=px, sem grupo, e a
    categoria vinha em número (1 e 3). Cada mês saiu duas vezes, 520 e 221.
    O grupo é deduzido do resultado: é a coluna que, com o mês, identifica a
    linha."""
    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "barras", "x": "competencia", "series": ["px"], "titulo": ""},
        resultado=PX_POR_CATEGORIA, texto="CAT 1 teve 617 PX em fev/2026.",
    )

    assert reply.raw_response["grafico"]["grupo"] == "categoria"


def test_eixo_repetido_sem_explicacao_nao_vira_grafico(conversa, catalogo):
    """Mês repetido sem coluna que diga por quê: o desenho seria de números
    que não se comparam. Melhor nenhum gráfico."""
    repetido = make_result(("competencia", "px"), [("2026-01-01", 520.0), ("2026-01-01", 221.0)])

    reply = _com_grafico(
        conversa, catalogo, {"tipo": "barras", "x": "competencia", "series": ["px"], "titulo": ""},
        resultado=repetido, texto="Foram 520 PX em jan/2026.",
    )

    assert "grafico" not in reply.raw_response


def test_separar_pedido_pela_redacao(conversa, catalogo):
    reply = _com_grafico(
        conversa, catalogo,
        {"tipo": "barras", "x": "competencia", "series": ["px"], "grupo": "categoria",
         "separar": True, "empilhado": True, "titulo": ""},
        resultado=PX_POR_CATEGORIA, texto="CAT 1 teve 617 PX em fev/2026.",
    )

    grafico = reply.raw_response["grafico"]
    assert grafico["separar"] is True and "empilhado" not in grafico


def _conversa_14(conversa, catalogo):
    """A resposta da conversa 14: texto, tabela e gráfico em blocos, gráfico
    sem grupo."""
    provider = ScriptedAIProvider(
        [plano()],
        [resposta("CAT 1 teve 617 PX em fev/2026.", blocos=(
            {"tipo": "texto", "texto": "CAT 1 teve 617 PX em fev/2026."},
            {"tipo": "tabela", "consulta": 0, "colunas": ["competencia", "categoria", "px"]},
            {"tipo": "grafico", "consulta": 0,
             "grafico": {"tipo": "barras", "x": "competencia", "series": ["px"], "titulo": ""}},
        ))],
    )
    reply = _responder(_pergunta(conversa, "PX de Neurologia CAT 1 e 3 por mês"), catalogo,
                       provider=provider, executor=FakeQueryExecutor([PX_POR_CATEGORIA]))
    assert reply.raw_response["blocos"][2]["tipo"] == "grafico"
    return reply


def test_separar_o_grafico_de_um_bloco_sem_ia_e_sem_banco(conversa, catalogo):
    """"O gráfico não ficou bom! eu quero ver CAT 1 e CAT 3 de forma
    separada": o gráfico estava num bloco, a regra não o via, e o pedido foi
    ao modelo, que refez a consulta e devolveu o mesmo desenho. Agora é ajuste
    de desenho, com o grupo que faltava."""
    _conversa_14(conversa, catalogo)
    provider = ScriptedAIProvider([], [])
    executor = FakeQueryExecutor()

    reply = _responder(
        _pergunta(conversa, "O gráfico não ficou bom! eu quero ver CAT 1 e CAT 3 de forma separada", client_id="c-9"),
        catalogo, provider=provider, executor=executor,
    )

    assert reply.rule == "ajuste_de_grafico"
    grafico = reply.raw_response["grafico"]
    assert grafico["grupo"] == "categoria" and grafico["separar"] is True
    assert reply.raw_response["grafico_de_consulta"] == 0
    assert "um gráfico por categoria" in reply.reply_text
    assert provider.plan_requests == [] and executor.executed == []


def test_ajuste_de_ajuste_continua_com_os_dados_da_consulta(conversa, catalogo):
    """"Separa" e depois "junta num gráfico só": o segundo ajuste lê o
    desenho do primeiro e os números da resposta que rodou a consulta."""
    original = _conversa_14(conversa, catalogo)
    _responder(_pergunta(conversa, "quero ver separado", client_id="c-9"), catalogo,
               provider=ScriptedAIProvider([], []), executor=FakeQueryExecutor())

    reply = _responder(_pergunta(conversa, "junta tudo no mesmo gráfico", client_id="c-10"), catalogo,
                       provider=ScriptedAIProvider([], []), executor=FakeQueryExecutor())

    assert reply.rule == "ajuste_de_grafico"
    assert "separar" not in reply.raw_response["grafico"]
    assert reply.raw_response["grafico"]["grupo"] == "categoria"
    assert reply.raw_response["grafico_de"] == original.message.replies.get().pk
