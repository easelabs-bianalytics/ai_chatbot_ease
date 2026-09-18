"""Provedor real da OpenAI, com o cliente de mentira (ADR-0016).

Nenhum teste aqui toca a rede: o que se prova é o contrato com o SDK (o que
mandamos, o que aceitamos de volta) e a conta de custo, que é o número que
vai parar no relatório e na decisão de trocar de modelo.
"""

import pytest

from ai_orchestrator.providers.base import (
    AIProviderError,
    AnswerRequest,
    HistoryMessage,
    Plan,
    PlanRequest,
)
from ai_orchestrator.providers.openai_provider import (
    OpenAIProvider,
    PlanoEstruturado,
    RespostaEstruturada,
    _custo,
)
from catalog.loader import load_catalog


class _Detalhes:
    def __init__(self, **campos):
        for nome, valor in campos.items():
            setattr(self, nome, valor)


class _Uso:
    def __init__(self, entrada, saida, cache=0, raciocinio=0):
        self.input_tokens = entrada
        self.output_tokens = saida
        self.input_tokens_details = _Detalhes(cached_tokens=cache)
        self.output_tokens_details = _Detalhes(reasoning_tokens=raciocinio)


class _Resposta:
    def __init__(self, conteudo, uso):
        self.output_parsed = conteudo
        self.usage = uso


class ClienteFalso:
    """Guarda o que foi enviado e devolve o que o teste programou."""

    def __init__(self, respostas):
        self._respostas = list(respostas)
        self.chamadas = []
        self.responses = self

    def parse(self, **kwargs):
        self.chamadas.append(kwargs)
        proximo = self._respostas.pop(0)
        if isinstance(proximo, Exception):
            raise proximo
        return proximo


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


def _plano(**campos):
    padrao = {
        "intent": "answer_with_data",
        "sql": "SELECT 1 FROM cddd.pdvs",
        "reference_query_id": "B13",
        "reason": "parte da B13",
    }
    return _Resposta(PlanoEstruturado(**{**padrao, **campos}), _Uso(20000, 900, cache=14000, raciocinio=600))


def _provider(catalogo, respostas):
    return OpenAIProvider(catalog=catalogo, client=ClienteFalso(respostas), model="gpt-5.6-terra",
                          answer_model="gpt-5.6-luna")


def test_planejamento_manda_prompt_contexto_recortado_e_pergunta(catalogo):
    provider = _provider(catalogo, [_plano()])

    plano = provider.plan(PlanRequest(question="Quais CDs estão em ruptura de Extrato?"))

    enviado = provider._client.chamadas[0]
    assert enviado["model"] == "gpt-5.6-terra"
    assert "Jarvis, copiloto de dados da Ease Labs" in enviado["instructions"]
    assert "Quais CDs estão em ruptura de Extrato?" in enviado["input"]
    assert "vw_forecast_projecao_cd" in enviado["input"]
    assert "fato_pbm_adesoes" not in enviado["input"]
    assert plano.intent == Plan.Intent.ANSWER_WITH_DATA
    assert plano.reference_query_id == "B13"


def test_chave_de_cache_e_o_tema_da_pergunta(catalogo):
    """O prefixo em cache custa um décimo; ele só é reaproveitado se
    perguntas do mesmo tema usarem a mesma chave."""
    provider = _provider(catalogo, [_plano()])

    provider.plan(PlanRequest(question="Quais CDs estão em ruptura de Extrato?"))

    assert provider._client.chamadas[0]["prompt_cache_key"] == "plano:planner_v1:estoque"


def test_data_de_hoje_vai_junto(catalogo):
    """Sem ela, "último trimestre" não tem como ser resolvido."""
    from datetime import date

    provider = _provider(catalogo, [_plano()])

    provider.plan(PlanRequest(question="Quantas prescrições tivemos no último trimestre?"))

    assert f"{date.today():%d/%m/%Y}" in provider._client.chamadas[0]["input"]


def test_correcao_leva_o_erro_anterior(catalogo):
    provider = _provider(catalogo, [_plano()])

    provider.plan(
        PlanRequest(question="quantas unidades?", error_note="a coluna 'und2' não existe")
    )

    assert "a coluna 'und2' não existe" in provider._client.chamadas[0]["input"]


def test_historico_entra_no_contexto(catalogo):
    provider = _provider(catalogo, [_plano()])

    provider.plan(
        PlanRequest(
            question="E em agosto?",
            history=(HistoryMessage(direction="in", text="Quanto o Hermes vendeu em julho?"),),
        )
    )

    assert "Quanto o Hermes vendeu em julho?" in provider._client.chamadas[0]["input"]


def test_custo_usa_o_preco_de_cache_para_o_que_veio_do_cache(catalogo):
    provider = _provider(catalogo, [_plano()])

    plano = provider.plan(PlanRequest(question="Quais CDs estão em ruptura de Extrato?"))

    # 6k a US$2,50, 14k a US$0,25 e 900 a US$12, por milhão.
    assert plano.usage.cost_estimate == pytest.approx(0.0293, abs=1e-6)
    assert plano.usage.tokens_input == 20000
    assert plano.usage.response["tokens_em_cache"] == 14000
    assert plano.usage.response["tokens_de_raciocinio"] == 600


def test_conta_de_custo_sem_cache():
    assert _custo("gpt-5.6-luna", 3000, 0, 500) == pytest.approx(0.0012, abs=1e-6)


def test_preco_do_planejador_e_o_da_fatura():
    """A tabela publicada dava US$ 2,00 de entrada para o Terra e a fatura
    cobrou como US$ 2,50 (conferido em 2026-09-17, US$ 1,16 no painel contra
    US$ 0,955 calculados). Preço subestimado vira teto de gasto que não
    segura nada."""
    assert _custo("gpt-5.6-terra", 1_000_000, 0, 0) == 2.50


def test_modelo_desconhecido_nao_inventa_custo():
    """Preço chutado só apareceria na fatura."""
    assert _custo("modelo-que-nao-existe", 100000, 0, 10000) == 0.0


def test_intencao_fora_do_contrato_vira_falha(catalogo):
    """Intenção que o orquestrador não conhece seguiria como "não sei" e
    esconderia um erro de integração."""
    provider = _provider(catalogo, [_plano(intent="talvez")])

    with pytest.raises(AIProviderError, match="intenção desconhecida"):
        provider.plan(PlanRequest(question="quantas unidades em agosto?"))


def test_falha_do_sdk_vira_erro_do_contrato(catalogo):
    provider = _provider(catalogo, [RuntimeError("connection reset")])

    with pytest.raises(AIProviderError, match="connection reset"):
        provider.plan(PlanRequest(question="quantas unidades em agosto?"))


def test_saida_nao_estruturada_vira_falha(catalogo):
    provider = _provider(catalogo, [_Resposta(None, _Uso(10, 10))])

    with pytest.raises(AIProviderError, match="saída estruturada"):
        provider.plan(PlanRequest(question="quantas unidades em agosto?"))


def test_redacao_recebe_o_resultado_e_nao_o_documento(catalogo):
    """É o corte que mais economiza: quem redige não precisa das regras de
    SQL (ADR-0015)."""
    resposta = _Resposta(
        RespostaEstruturada(reply="Foram 47 unidades em ago/2026.", caveats=["parcial"]),
        _Uso(2800, 120),
    )
    provider = _provider(catalogo, [resposta])

    saida = provider.answer(
        AnswerRequest(
            question="quantas unidades em agosto?",
            sql="SELECT SUM(und) FROM cddd.fato_cdd",
            columns=("unidades",),
            rows=((47,),),
            truncated=False,
            reference_query_id="B10",
        )
    )

    enviado = provider._client.chamadas[0]
    assert enviado["model"] == "gpt-5.6-luna"
    assert '"unidades": 47' in enviado["input"]
    assert "-- B10 ·" not in enviado["input"]
    assert saida.reply.startswith("Foram 47")
    assert saida.caveats == ("parcial",)


def test_resultado_cortado_e_avisado_a_quem_redige(catalogo):
    resposta = _Resposta(RespostaEstruturada(reply="São pelo menos 500 linhas."), _Uso(3000, 100))
    provider = _provider(catalogo, [resposta])

    provider.answer(
        AnswerRequest(question="liste os PDVs", sql="SELECT 1", columns=("pdv",),
                      rows=(("x",),), truncated=True)
    )

    assert "cortado no limite" in provider._client.chamadas[0]["input"]


def test_reescrita_diz_qual_numero_nao_tinha_suporte(catalogo):
    resposta = _Resposta(RespostaEstruturada(reply="Foram 47 unidades."), _Uso(3000, 100))
    provider = _provider(catalogo, [resposta])

    provider.answer(
        AnswerRequest(question="quantas unidades?", sql="SELECT 1", columns=("und",),
                      rows=((47,),), truncated=False, revision_note="o número 1.200 não está no resultado")
    )

    assert "1.200 não está no resultado" in provider._client.chamadas[0]["input"]


def test_resposta_vazia_vira_falha(catalogo):
    provider = _provider(catalogo, [_Resposta(RespostaEstruturada(reply="   "), _Uso(10, 10))])

    with pytest.raises(AIProviderError, match="vazia"):
        provider.answer(
            AnswerRequest(question="q", sql="SELECT 1", columns=("a",), rows=((1,),), truncated=False)
        )


class _ErroDaOpenAI(Exception):
    """Imita o APIStatusError do SDK: `code` vem do corpo da resposta."""

    def __init__(self, mensagem, code=None, body=None):
        super().__init__(mensagem)
        self.code = code
        self.body = body


def test_credito_esgotado_vira_erro_proprio(catalogo):
    """Com o limite de gasto atingido, a OpenAI responde 429 com
    `insufficient_quota`. Tratar como falha passageira faria o sistema
    insistir e o usuário ver "tive um problema técnico"."""
    from ai_orchestrator.providers.base import AIQuotaExceeded

    erro = _ErroDaOpenAI("You exceeded your current quota", code="insufficient_quota")
    provider = _provider(catalogo, [erro])

    with pytest.raises(AIQuotaExceeded):
        provider.plan(PlanRequest(question="quantas unidades em agosto?"))


def test_credito_esgotado_reconhecido_pelo_corpo_da_resposta(catalogo):
    from ai_orchestrator.providers.base import AIQuotaExceeded

    erro = _ErroDaOpenAI("erro 429", body={"error": {"code": "billing_hard_limit_reached"}})
    provider = _provider(catalogo, [erro])

    with pytest.raises(AIQuotaExceeded):
        provider.plan(PlanRequest(question="quantas unidades em agosto?"))


def test_limite_de_velocidade_continua_falha_passageira(catalogo):
    """O 429 de requisições demais passa sozinho: esse sim vai para o retry."""
    from ai_orchestrator.providers.base import AIQuotaExceeded

    erro = _ErroDaOpenAI("Rate limit reached", code="rate_limit_exceeded")
    provider = _provider(catalogo, [erro])

    with pytest.raises(AIProviderError) as capturado:
        provider.plan(PlanRequest(question="quantas unidades em agosto?"))
    assert not isinstance(capturado.value, AIQuotaExceeded)


# --- planilha e gráfico (ADR-0020) -----------------------------------------


def test_pedido_de_planilha_chega_no_plano(catalogo):
    provider = _provider(catalogo, [_plano(excel=True)])

    plano = provider.plan(PlanRequest(question="me manda os PDVs de SP em excel"))

    assert plano.excel is True


def test_sugestao_de_grafico_volta_junto_com_a_resposta(catalogo):
    """O provedor só transporta a sugestão; quem confere contra o resultado
    é o orquestrador."""
    from ai_orchestrator.providers.openai_provider import GraficoEstruturado

    saida = _Resposta(
        RespostaEstruturada(
            reply="Foram 777 unidades em ago/2026.",
            grafico=GraficoEstruturado(tipo="linha", x="mes", series=["unidades"], titulo="Unidades por mês"),
        ),
        _Uso(3000, 120),
    )
    provider = _provider(catalogo, [saida])

    resposta = provider.answer(
        AnswerRequest(question="unidades por mês", sql="SELECT 1", columns=("mes", "unidades"),
                      rows=(("2026-08", 777),), truncated=False)
    )

    assert resposta.chart == {"tipo": "linha", "x": "mes", "series": ["unidades"], "titulo": "Unidades por mês"}


def test_lista_longa_manda_a_redacao_apontar_para_a_planilha(catalogo):
    """Despejar 200 linhas numa bolha de conversa é ilegível — e o resultado
    inteiro está no botão de download."""
    saida = _Resposta(RespostaEstruturada(reply="São 200 PDVs."), _Uso(3000, 100))
    provider = _provider(catalogo, [saida])

    provider.answer(
        AnswerRequest(question="liste os PDVs", sql="SELECT 1", columns=("pdv",),
                      rows=(("x",),), truncated=False, total_rows=200)
    )

    entrada = provider._client.chamadas[0]["input"]
    assert "Total de linhas no resultado: 200" in entrada
    assert "Baixar Excel" in entrada


def test_quando_o_usuario_pediu_excel_a_resposta_nao_repete_a_lista(catalogo):
    saida = _Resposta(RespostaEstruturada(reply="A planilha traz os 200 PDVs."), _Uso(3000, 100))
    provider = _provider(catalogo, [saida])

    provider.answer(
        AnswerRequest(question="me manda em excel", sql="SELECT 1", columns=("pdv",),
                      rows=(("x",),), truncated=False, total_rows=200, excel=True)
    )

    assert "# Planilha" in provider._client.chamadas[0]["input"]


def test_consulta_vazia_pede_a_verificacao_no_plano(catalogo):
    """O planejador precisa saber que a consulta voltou vazia — senão ele
    reescreve a mesma pergunta e o resultado é vazio de novo."""
    provider = _provider(catalogo, [_plano()])

    provider.plan(PlanRequest(question="sell out do Ricardo em ago/26",
                              empty_note="A consulta rodou sem erro e não retornou nenhuma linha."))

    entrada = provider._client.chamadas[0]["input"]
    assert "não retornou nenhuma linha" in entrada
    assert "verificação" in entrada


def test_redacao_da_verificacao_sabe_que_o_numero_nao_e_a_resposta(catalogo):
    saida = _Resposta(RespostaEstruturada(reply="Esse representante saiu em maio."), _Uso(3000, 100))
    provider = _provider(catalogo, [saida])

    provider.answer(
        AnswerRequest(question="sell out do Ricardo Reis em ago/26", sql="SELECT 1",
                      columns=("nome", "data_demissao"), rows=(("Ricardo Reis", "2026-05-18"),),
                      truncated=False, verification=True)
    )

    entrada = provider._client.chamadas[0]["input"]
    assert "Consulta de verificação" in entrada
    assert "não apresente esses números" in entrada.lower()


def test_resultado_inteiro_manda_a_tabela_sair_completa(catalogo):
    """A tabela vinha cortada em 20 linhas mesmo quando o resultado cabia
    inteiro no que a redação recebeu (2026-09-18)."""
    saida = _Resposta(RespostaEstruturada(reply="São 31 CDs em ruptura."), _Uso(3000, 100))
    provider = _provider(catalogo, [saida])

    provider.answer(
        AnswerRequest(question="quais CDs estão em ruptura?", sql="SELECT 1",
                      columns=("cd",), rows=tuple((f"CD{n}",) for n in range(31)),
                      truncated=False, total_rows=31)
    )

    entrada = provider._client.chamadas[0]["input"]
    assert "todas as 31 linhas, sem cortar" in entrada
    assert "Lista longa" not in entrada
