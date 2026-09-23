"""Provedor real com anexo (ADR-0024), com o cliente de mentira.

Achado de 2026-09-21: "pode preencher o que está faltando" não tem palavra
de tema nenhuma; os cabeçalhos da planilha têm. E a segunda chamada ao
planejador saía sem a planilha.
"""

from ai_orchestrator.providers.base import PlanRequest
from ai_orchestrator.providers.openai_provider import ColunaPreenchida, PreenchimentoEstruturado
from tests.unit.test_openai_provider import _plano, _provider, _texto, catalogo  # noqa: F401

PLANILHA_DE_REPRESENTANTES = (
    "Arquivo: dados_representantes.xlsx\nLinhas de dados: 3\n"
    "Colunas (nome · tipo · exemplos):\n- REPRESENTANTE · texto · MARTA ELOISA\n"
    "- PX EASE YTD 2026 · vazia\n- UNIDADES EASE SELL OUT AGO/2026 · vazia\n"
    "- MKT SHARE EASE VAREJO YTD 2026 · vazia"
)


def test_secoes_do_plano_saem_tambem_dos_cabecalhos_da_planilha(catalogo):
    provider = _provider(catalogo, [_plano()])

    plano = provider.plan(PlanRequest(
        question="Pode preencher para mim o que está faltando", planilha=PLANILHA_DE_REPRESENTANTES,
    ))

    secoes = plano.usage.request["secoes"]
    assert "prescricao" in secoes and "sell_out" in secoes


def test_planilha_vai_ao_modelo_mesmo_com_o_documento_inteiro(catalogo):
    provider = _provider(catalogo, [_plano()])

    provider.plan(PlanRequest(question="preencha", planilha=PLANILHA_DE_REPRESENTANTES, full_context=True))

    assert "PX EASE YTD 2026" in _texto(provider._client.chamadas[0])


def test_preenchimento_de_varias_colunas_e_lido(catalogo):
    preenchimento = PreenchimentoEstruturado(
        coluna_chave="REPRESENTANTE",
        chave_no_resultado="representante",
        colunas=[
            ColunaPreenchida(coluna_destino="PX EASE YTD 2026", valor_no_resultado="px_ease"),
            ColunaPreenchida(coluna_destino="UNIDADES EASE SELL OUT AGO/2026", valor_no_resultado="und"),
        ],
    )
    provider = _provider(catalogo, [_plano(preenchimento=preenchimento)])

    plano = provider.plan(PlanRequest(question="preencha", planilha=PLANILHA_DE_REPRESENTANTES))

    assert plano.preenchimento == {
        "coluna_chave": "REPRESENTANTE",
        "chave_no_resultado": "representante",
        "colunas": [
            {"coluna_destino": "PX EASE YTD 2026", "valor_no_resultado": "px_ease"},
            {"coluna_destino": "UNIDADES EASE SELL OUT AGO/2026", "valor_no_resultado": "und"},
        ],
        # Arquivo de uma aba só: o plano não precisa nomear nenhuma.
        "aba": "",
    }


def test_preenchimento_incompleto_e_descartado(catalogo):
    incompleto = PreenchimentoEstruturado(coluna_chave="REPRESENTANTE")
    provider = _provider(catalogo, [_plano(preenchimento=incompleto)])

    plano = provider.plan(PlanRequest(question="preencha", planilha=PLANILHA_DE_REPRESENTANTES))

    assert plano.preenchimento == {}


def test_preenchimento_sem_planilha_anexada_e_ignorado(catalogo):
    inventado = PreenchimentoEstruturado(
        coluna_chave="a",
        chave_no_resultado="b",
        colunas=[ColunaPreenchida(coluna_destino="c", valor_no_resultado="d")],
    )
    provider = _provider(catalogo, [_plano(preenchimento=inventado)])

    assert provider.plan(PlanRequest(question="quanto vendemos?")).preenchimento == {}


def test_com_planilha_os_tres_temas_vao_completos(catalogo):
    """No caso real, a prescrição foi como resumo, o modelo pediu o documento
    inteiro e a chamada custou US$ 0,125."""
    provider = _provider(catalogo, [_plano()])

    provider.plan(PlanRequest(question="preencha", planilha=PLANILHA_DE_REPRESENTANTES))

    texto = _texto(provider._client.chamadas[0])
    assert texto.count("Tema relacionado:") == 2
    assert "(resumo)" not in texto


def test_sem_planilha_o_terceiro_tema_continua_em_resumo(catalogo):
    """Pergunta comum não muda de custo."""
    provider = _provider(catalogo, [_plano()])

    provider.plan(PlanRequest(question="PX por representante e sell out em unidades por setor do painel"))

    assert "Tema relacionado (resumo):" in _texto(provider._client.chamadas[0])


def test_ressalva_de_forecast_e_lida_do_plano(catalogo):
    """Marcada pelo modelo só em projeção de Sell Out ou Sell In da Ease."""
    provider = _provider(catalogo, [_plano(ressalva_forecast=True), _plano()])

    com = provider.plan(PlanRequest(question="projeção de sell out de outubro"))
    sem = provider.plan(PlanRequest(question="projeção de PX de outubro"))

    assert com.ressalva_forecast is True
    assert sem.ressalva_forecast is False
