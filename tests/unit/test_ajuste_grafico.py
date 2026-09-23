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
        ("muda para pizza", {"tipo": "pizza"}),
        ("troca para área", {"tipo": "area"}),
        ("empilha as barras", {"empilhado": True}),
        # conversa 14 (2026-09-23)
        ("O gráfico não ficou bom! eu quero ver CAT 1 e CAT 3 de forma separada", {"separar": True}),
        ("faz um gráfico para cada categoria", {"separar": True}),
        ("junta tudo no mesmo gráfico", {"separar": False}),
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


@pytest.mark.parametrize(
    "mensagem",
    [
        # 2026-09-23: abrir por uma categoria é dado novo, não troca de desenho
        "Mude a visualização para barra e empilhe por especialidade",
        "muda para barras por rede",
    ],
)
def test_abrir_por_categoria_fica_com_a_ia(mensagem):
    assert ler_ajuste(mensagem) is None


def test_empilhar_troca_a_linha_por_barras():
    assert aplicar({"tipo": "linha", "x": "mes", "series": ["a", "b"]}, {"empilhado": True}) == {
        "tipo": "barras", "x": "mes", "series": ["a", "b"], "empilhado": True,
    }


def test_separar_tira_o_empilhado():
    novo = aplicar({"tipo": "barras", "x": "mes", "series": ["px"], "grupo": "cat", "empilhado": True},
                   {"separar": True})

    assert novo["separar"] is True and "empilhado" not in novo


def test_texto_do_separar_diz_por_qual_coluna():
    assert "um gráfico por categoria" in descrever({"separar": True}, total=16, grupo="categoria")
