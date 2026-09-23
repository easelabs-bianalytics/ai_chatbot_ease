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
from ai_orchestrator.prompts import PROMPT_VERSION
from catalog.loader import load_catalog


class _Detalhes:
    def __init__(self, **campos):
        for nome, valor in campos.items():
            setattr(self, nome, valor)


class _Uso:
    def __init__(self, entrada, saida, cache=0, raciocinio=0, gravado=0):
        self.input_tokens = entrada
        self.output_tokens = saida
        self.input_tokens_details = _Detalhes(cached_tokens=cache, cache_write_tokens=gravado)
        self.output_tokens_details = _Detalhes(reasoning_tokens=raciocinio)


def _texto(chamada):
    """O que o modelo lê, em texto corrido. O planejamento manda a entrada em
    blocos (por causa do breakpoint do cache); a redação, como string."""
    entrada = chamada["input"]
    if isinstance(entrada, str):
        return entrada
    return "".join(bloco["text"] for msg in entrada for bloco in msg["content"])


def _blocos(chamada):
    return [bloco for msg in chamada["input"] for bloco in msg["content"]]


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
    assert "Quais CDs estão em ruptura de Extrato?" in _texto(enviado)
    assert "vw_forecast_projecao_cd" in _texto(enviado)
    assert "fato_pbm_adesoes" not in _texto(enviado)
    assert plano.intent == Plan.Intent.ANSWER_WITH_DATA
    assert plano.reference_query_id == "B13"


def test_conversa_curta_vai_ao_modelo_barato(catalogo):
    """"Oi, quem é você?" custou US$ 0,032 no modelo principal (2026-09-23),
    o preço de uma consulta. Sem tema e curta, vai primeiro ao barato."""
    provider = _provider(catalogo, [_plano(intent="conversation", sql="", user_message="Sou o Jarvis.")])

    plano = provider.plan(PlanRequest(question="Oi, quem é você?"))

    assert [c["model"] for c in provider._client.chamadas] == ["gpt-5.6-luna"]
    assert plano.intent == Plan.Intent.CONVERSATION
    assert plano.tentativas == ()


def test_conversa_curta_que_era_dado_sobe_para_o_principal(catalogo):
    """Se o barato vê que é pergunta de dado, quem escreve o SQL é o principal
    — e a tentativa barata fica registrada, porque foi paga."""
    provider = _provider(catalogo, [_plano(), _plano()])

    plano = provider.plan(PlanRequest(question="e em julho, como ficou?"))

    assert [c["model"] for c in provider._client.chamadas] == ["gpt-5.6-luna", "gpt-5.6-terra"]
    assert plano.intent == Plan.Intent.ANSWER_WITH_DATA
    assert [u.model for u in plano.tentativas] == ["gpt-5.6-luna"]


def test_pergunta_com_tema_vai_direto_ao_principal(catalogo):
    provider = _provider(catalogo, [_plano()])

    provider.plan(PlanRequest(question="Quais CDs estão em ruptura?"))

    assert [c["model"] for c in provider._client.chamadas] == ["gpt-5.6-terra"]


def test_chave_de_cache_do_plano_nao_carrega_o_tema(catalogo):
    """A chave roteia a requisição. Uma por tema fragmentava o roteamento: a
    pergunta de estoque não reaproveitava o prefixo comum — prompt mais
    núcleo, ~5,8 mil tokens iguais em toda pergunta — que a de sell-out tinha
    acabado de aquecer. Medido em 2026-09-18: 20% de cache no plano contra
    42% na redação, que sempre usou chave fixa."""
    provider = _provider(catalogo, [_plano(), _plano()])

    provider.plan(PlanRequest(question="Quais CDs estão em ruptura de Extrato?"))
    provider.plan(PlanRequest(question="Quantas prescrições tivemos em agosto?"))

    chaves = [c["prompt_cache_key"] for c in provider._client.chamadas]
    assert chaves == [f"plano:{PROMPT_VERSION}", f"plano:{PROMPT_VERSION}"]


def test_data_de_hoje_vai_junto(catalogo):
    """Sem ela, "último trimestre" não tem como ser resolvido."""
    from datetime import date

    provider = _provider(catalogo, [_plano()])

    provider.plan(PlanRequest(question="Quantas prescrições tivemos no último trimestre?"))

    assert f"{date.today():%d/%m/%Y}" in _texto(provider._client.chamadas[0])


def test_correcao_leva_o_erro_anterior(catalogo):
    provider = _provider(catalogo, [_plano()])

    provider.plan(
        PlanRequest(question="quantas unidades?", error_note="a coluna 'und2' não existe")
    )

    assert "a coluna 'und2' não existe" in _texto(provider._client.chamadas[0])


def test_historico_entra_no_contexto(catalogo):
    provider = _provider(catalogo, [_plano()])

    provider.plan(
        PlanRequest(
            question="E em agosto?",
            history=(HistoryMessage(direction="in", text="Quanto o Hermes vendeu em julho?"),),
        )
    )

    assert "Quanto o Hermes vendeu em julho?" in _texto(provider._client.chamadas[0])


def test_custo_usa_o_preco_de_cache_para_o_que_veio_do_cache(catalogo):
    provider = _provider(catalogo, [_plano()])

    plano = provider.plan(PlanRequest(question="Quais CDs estão em ruptura de Extrato?"))

    # 6k a US$2,00, 14k a US$0,20 e 900 a US$12, por milhão.
    assert plano.usage.cost_estimate == pytest.approx(0.0256, abs=1e-6)
    assert plano.usage.tokens_input == 20000
    assert plano.usage.response["tokens_em_cache"] == 14000
    assert plano.usage.response["tokens_de_raciocinio"] == 600


def test_conta_de_custo_sem_cache():
    assert _custo("gpt-5.6-luna", 3000, 0, 500) == pytest.approx(0.0012, abs=1e-6)


def test_gravar_no_cache_custa_mais_que_a_entrada_comum():
    """No GPT-5.6 a gravação custa 1,25× a entrada.

    Em 2026-09-17 a conta daqui não fechava com a fatura e a entrada do Terra
    foi "calibrada" para US$ 2,50 — que era o preço de gravação. A conta
    fechava por acaso, porque no modo implícito quase toda entrada é gravada.
    Com o cache explícito só o prefixo fixo é gravado, e as duas coisas
    precisam ser contadas separadas para o relatório bater com a fatura."""
    assert _custo("gpt-5.6-terra", 1_000_000, 0, 0) == 2.00
    assert _custo("gpt-5.6-terra", 1_000_000, 0, 0, gravado=1_000_000) == 2.50
    # 10k comuns, 5k lidos do cache, 5k gravados e 500 de saída:
    # 10k×2,00 + 5k×0,20 + 5k×2,50 + 500×12 = 20000+1000+12500+6000
    assert _custo("gpt-5.6-terra", 20_000, 5_000, 500, gravado=5_000) == pytest.approx(0.0395, abs=1e-6)


def test_custo_registra_o_que_foi_gravado_no_cache(catalogo):
    provider = _provider(catalogo, [
        _Resposta(PlanoEstruturado(intent="answer_with_data", sql="SELECT 1 FROM cddd.pdvs",
                                   reference_query_id="B13", reason="x"),
                  _Uso(20000, 500, cache=0, gravado=5000)),
    ])

    plano = provider.plan(PlanRequest(question="Quais CDs estão em ruptura de Extrato?"))

    # 15k×2,00 + 5k×2,50 + 500×12
    assert plano.usage.cost_estimate == pytest.approx(0.0485, abs=1e-6)
    assert plano.usage.response["tokens_gravados_no_cache"] == 5000


def test_planejamento_grava_no_cache_o_fixo_e_o_tema(catalogo):
    """No modo implícito a OpenAI gravava o prompt inteiro a cada chamada, a
    1,25× o preço da entrada. Com um ponto de cache só, no prefixo fixo, as
    seções do tema e o schema pagavam entrada cheia em toda pergunta — 35% de
    cache, medido em 2026-09-22. Com dois pontos, a segunda pergunta do mesmo
    tema lê ~90% da entrada a um décimo do preço."""
    provider = _provider(catalogo, [_plano()])

    provider.plan(PlanRequest(question="Quais CDs estão em ruptura de Extrato?"))

    enviado = provider._client.chamadas[0]
    assert enviado["prompt_cache_options"] == {"mode": "explicit"}
    blocos = _blocos(enviado)
    marcados = [b for b in blocos if "prompt_cache_breakpoint" in b]
    assert len(marcados) == 2
    assert blocos[:2] == marcados, "os pontos fecham o fixo e o tema, nessa ordem"
    # 1) o fixo: igual em toda pergunta
    assert "Temas do documento" in blocos[0]["text"]
    assert "Tema da pergunta" not in blocos[0]["text"]
    # 2) o tema: igual em toda pergunta do mesmo assunto
    assert "Tema da pergunta" in blocos[1]["text"]
    assert "vw_forecast_projecao_cd" in blocos[1]["text"]
    # 3) o resto: a pergunta do usuário, que muda sempre. (O texto dela pode
    # aparecer no tema: o documento usa perguntas de exemplo.)
    assert "# Pergunta do usuário" in blocos[2]["text"]
    assert "Quais CDs estão em ruptura de Extrato?" in blocos[2]["text"]
    assert "# Pergunta do usuário" not in blocos[0]["text"] + blocos[1]["text"]


def test_prefixo_gravado_e_o_mesmo_para_perguntas_diferentes(catalogo):
    """É o que faz valer a pena: a pergunta de estoque reaproveita o que a de
    prescrição acabou de gravar."""
    provider = _provider(catalogo, [_plano(), _plano()])

    provider.plan(PlanRequest(question="Quais CDs estão em ruptura de Extrato?"))
    provider.plan(PlanRequest(question="Quantas prescrições tivemos em agosto?"))

    primeiro, segundo = (_blocos(c)[0]["text"] for c in provider._client.chamadas)
    assert primeiro == segundo


def test_dividir_em_blocos_nao_muda_o_que_o_modelo_le(catalogo):
    """O cache explícito só muda o que a OpenAI guarda. Se o texto emendado
    dos blocos diferisse do contexto de antes, a resposta poderia mudar."""
    from ai_orchestrator.context import montar_contexto_do_plano

    provider = _provider(catalogo, [_plano()])
    pergunta = "Quais CDs estão em ruptura de Extrato?"

    provider.plan(PlanRequest(question=pergunta))

    contexto = montar_contexto_do_plano(catalogo, pergunta)
    assert _texto(provider._client.chamadas[0]).startswith(contexto.texto)


def test_contexto_completo_nao_grava_nada_no_cache(catalogo):
    """Os ~45 mil tokens do documento inteiro nunca foram reaproveitados (0% de
    cache nas três vezes medidas). Gravar só pagaria o ágio."""
    provider = _provider(catalogo, [_plano()])

    provider.plan(PlanRequest(question="Quais CDs estão em ruptura de Extrato?", full_context=True))

    blocos = _blocos(provider._client.chamadas[0])
    assert len(blocos) == 1
    assert "prompt_cache_breakpoint" not in blocos[0]


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

    assert resposta.chart == {
        "tipo": "linha", "x": "mes", "series": ["unidades"], "grupo": "", "empilhado": False,
        "titulo": "Unidades por mês",
    }


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

    entrada = _texto(provider._client.chamadas[0])
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
