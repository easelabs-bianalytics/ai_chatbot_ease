"""Tabela com propósito (conversa 24, 2026-09-24).

A projeção de PX saiu com nove colunas, cinco delas o mesmo valor repetido
nas doze linhas. Coluna constante que só repete um resumo (uma data, ou um
número que o texto já cita) sai da tabela; a planilha continua com todas.
"""

from types import SimpleNamespace

from ai_orchestrator import orchestrator
from datasource.executors.fake import make_result

COLUNAS = ("mes", "tipo", "px", "tendencia_px", "variacao_tendencia_px_mes", "ultimo_mes_realizado",
           "px_realizado_2026", "px_projetado_restante", "px_projecao_total_2026")
RESUMO = (124.2, "2026-08-01", 40531.0, 23246.0, 63777.0)
PROJECAO = make_result(COLUNAS, [
    ("2026-01-01", "realizado", 4327.0, 4632.0, *RESUMO),
    ("2026-02-01", "realizado", 4821.0, 4756.0, *RESUMO),
    ("2026-03-01", "realizado", 4871.0, 4880.0, *RESUMO),
    ("2026-04-01", "realizado", 5258.0, 5004.0, *RESUMO),
    ("2026-05-01", "realizado", 5514.0, 5128.0, *RESUMO),
    ("2026-06-01", "realizado", 5102.0, 5253.0, *RESUMO),
    ("2026-07-01", "realizado", 5295.0, 5377.0, *RESUMO),
    ("2026-08-01", "realizado", 5343.0, 5501.0, *RESUMO),
    ("2026-09-01", "projetado", 5625.0, 5625.0, *RESUMO),
    ("2026-10-01", "projetado", 5749.0, 5749.0, *RESUMO),
    ("2026-11-01", "projetado", 5874.0, 5874.0, *RESUMO),
    ("2026-12-01", "projetado", 5998.0, 5998.0, *RESUMO),
])
TEXTO = (
    "A projeção prescritiva da Ease Labs para o fechamento de 2026 é de **63.777 PX**. Até ago/2026, "
    "foram realizados **40.531 PX**; a estimativa para set a dez/2026 é de 23.246 PX. A projeção é "
    "uma estimativa baseada na tendência linear dos meses fechados, com crescimento de 124,2 PX por mês."
)
PODADAS = ["mes", "tipo", "px", "tendencia_px"]


def test_coluna_repetida_em_todas_as_linhas_sai_da_tabela():
    """A redação pediu as nove; as cinco que repetem o resumo saem."""
    assert orchestrator._colunas_da_tabela(list(COLUNAS), PROJECAO, TEXTO) == PODADAS


def test_sem_pedido_tambem_poda():
    assert orchestrator._colunas_da_tabela(None, PROJECAO, TEXTO) == PODADAS


def test_a_ordem_pedida_e_mantida():
    assert orchestrator._colunas_da_tabela(["px", "mes", "px_projecao_total_2026"], PROJECAO, TEXTO) == ["px", "mes"]


def test_numero_constante_que_o_texto_nao_cita_fica():
    """Todos os CDs com DDE 0 é a informação da lista, não um resumo."""
    ruptura = make_result(("cd", "dde"), [(f"CD {i}", 0.0) for i in range(5)])

    assert orchestrator._colunas_da_tabela(None, ruptura, "Cinco CDs estão em ruptura.") == ["cd", "dde"]


def test_data_repetida_em_todas_as_linhas_sai():
    """A data de corte é contexto: o texto cita uma vez."""
    lista = make_result(("cd", "dde", "data_estoque"), [(f"CD {i}", float(i), "2026-09-20") for i in range(4)])

    assert orchestrator._colunas_da_tabela(None, lista, "") == ["cd", "dde"]


def test_com_uma_ou_duas_linhas_a_constante_pode_ser_a_resposta():
    duas = make_result(("rede", "px", "total"), [("A", 10.0, 30.0), ("B", 20.0, 30.0)])

    assert orchestrator._colunas_da_tabela(None, duas) == ["rede", "px", "total"]


def test_tudo_constante_nao_vira_tabela_vazia():
    iguais = make_result(("rede", "px"), [("A", 1.0)] * 3)

    assert orchestrator._colunas_da_tabela(None, iguais) == ["rede", "px"]


def test_bloco_de_tabela_da_conversa_24_sai_podado():
    blocos = [
        {"tipo": "texto", "texto": TEXTO},
        {"tipo": "tabela", "consulta": 0, "colunas": list(COLUNAS)},
    ]

    validos, _ = orchestrator._validar_blocos(blocos, [(PROJECAO, "select 1")], SimpleNamespace(content="projeção"))

    assert validos[1]["colunas"] == PODADAS
