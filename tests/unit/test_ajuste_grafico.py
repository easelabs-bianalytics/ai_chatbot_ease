"""Ajuste do gráfico pela conversa (regra, sem IA e sem banco).

O risco desta regra é sequestrar pergunta de dado: "quantas unidades por
linha de produto" tem 'linha' no meio e não pode virar troca de gráfico.
Metade dos testes aqui é sobre o que ela NÃO pode capturar.
"""

import pytest

from ai_orchestrator.ajuste_grafico import aplicar, descrever, ler_ajuste


@pytest.mark.parametrize(
    "mensagem,esperado",
    [
        ("muda para barras", {"tipo": "barras"}),
        ("Troque para linha", {"tipo": "linha"}),
        ("coloca em barras horizontais", {"tipo": "barras_horizontais"}),
        ("deixa o gráfico em colunas", {"tipo": "barras"}),
        ("só os 5 primeiros", {"limite": 5}),
        ("top 10", {"limite": 10}),
        ("mostra os 3 maiores", {"limite": 3}),
        ("muda para barras e só os 8 primeiros", {"tipo": "barras", "limite": 8}),
        ("mostra todos no gráfico", {"limite": 0}),
    ],
)
def test_le_o_pedido_de_ajuste(mensagem, esperado):
    assert ler_ajuste(mensagem) == esperado


@pytest.mark.parametrize(
    "mensagem",
    [
        "quantas unidades por linha de produto em agosto de 2026?",
        "qual a venda por canal e por linha?",
        "quais PDVs tiveram as maiores vendas em julho de 2026 no Ceará?",
        "me manda a lista completa dos PDVs da Pague Menos no Ceará em excel",
        "e em julho?",
        "",
    ],
)
def test_nao_sequestra_pergunta_de_dado(mensagem):
    assert ler_ajuste(mensagem) is None


def test_mensagem_longa_nao_e_ajuste():
    """Ajuste é pedido curto. Frase comprida é pergunta, mesmo citando
    'barras'."""
    longa = "eu queria entender melhor se dá para ver isso em barras junto com a evolução do estoque"

    assert ler_ajuste(longa) is None


def test_aplicar_preserva_o_que_nao_foi_pedido():
    grafico = {"tipo": "linha", "x": "mes", "series": ["und"], "titulo": "Unidades"}

    novo = aplicar(grafico, {"tipo": "barras"})

    assert novo["tipo"] == "barras"
    assert novo["x"] == "mes" and novo["series"] == ["und"] and novo["titulo"] == "Unidades"


def test_aplicar_limite_e_depois_tirar():
    grafico = {"tipo": "barras", "x": "cd", "series": ["dde"]}

    com_corte = aplicar(grafico, {"limite": 5})
    sem_corte = aplicar(com_corte, {"limite": 0})

    assert com_corte["limite"] == 5
    assert "limite" not in sem_corte


def test_texto_avisa_que_a_tabela_nao_encolheu():
    """Cortar o desenho e deixar a tabela inteira confunde se ninguém disser."""
    texto = descrever({"limite": 5}, total=31)

    assert "5 primeiros" in texto
    assert "31 linhas" in texto


def test_texto_sem_corte_nao_fala_de_tabela():
    assert "tabela" not in descrever({"tipo": "barras"}, total=31)
