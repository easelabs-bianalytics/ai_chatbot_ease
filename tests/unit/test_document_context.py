"""Recorte do documento por tema (ADR-0015).

O corte é o que segura o custo, e é também o que pode fazer a IA perder uma
regra. Cada teste aqui fixa uma dessas duas coisas: o que sempre vai junto e
o que só vai quando o tema pede.
"""

import pytest

from ai_orchestrator.context import (
    escolher_secoes,
    filtrar_schema,
    montar_contexto_da_resposta,
    montar_contexto_do_plano,
    pontuar,
)
from ai_orchestrator.document import CHAVES, get_document, parse_document
from ai_orchestrator.providers.base import HistoryMessage
from catalog.loader import load_catalog


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


@pytest.fixture(scope="module")
def documento(catalogo):
    return get_document(catalogo)


def test_documento_vira_as_cinco_secoes_do_time_de_bi(documento):
    assert [s.chave for s in documento.secoes] == list(CHAVES)
    assert documento.preambulo.startswith("# Referência de consultas")


def test_preambulo_traz_as_regras_que_valem_para_tudo(documento):
    """Elas viajam em toda pergunta: é o preâmbulo que manda não inventar
    dado que não existe e avisar com cordialidade."""
    assert "não invente a resposta" in documento.preambulo
    assert "referência, não resposta pronta" in documento.preambulo


def test_cada_referencia_fica_na_secao_dela(documento, catalogo):
    por_secao = {r for s in documento.secoes for r in s.referencias}

    assert por_secao == {r.id for r in catalogo.references}
    assert "B13" in documento.por_chave("sell_out").referencias
    assert "C20" in documento.por_chave("estoque").referencias


def test_resumo_perde_as_consultas_mas_mantem_tabelas_e_regras(documento):
    """A seção vizinha existe para a IA saber onde o dado mora e que regra
    vale; as consultas inteiras seriam o grosso dos tokens."""
    estoque = documento.por_chave("estoque")

    assert "```sql" not in estoque.resumo
    assert "vw_estoque_cd_recente" in estoque.resumo
    assert "dde_base" in estoque.resumo
    # Quanto encolhe depende de quanta regra em prosa o time de BI escreveu;
    # o que o resumo garante é tirar as consultas, que são o grosso.
    assert len(estoque.resumo) < len(estoque.texto) * 0.7


def test_tabelas_da_secao_saem_do_texto_e_das_consultas(documento):
    sell_out = documento.por_chave("sell_out")

    assert "cddd.fato_cdd" in sell_out.tabelas
    assert "td.fato_td" in sell_out.tabelas
    assert "cddd.informantes" in sell_out.tabelas


def test_documento_sem_secao_falha_alto():
    with pytest.raises(ValueError, match="sem seções"):
        parse_document("texto solto, sem cabeçalho nenhum")


# --- roteador -------------------------------------------------------------


@pytest.mark.parametrize(
    "pergunta,esperada",
    [
        ("Quantas prescrições a Ease teve em agosto?", "prescricao"),
        ("Quantas unidades a Raia dispensou por mês?", "sell_out"),
        ("Qual o faturamento do mercado varejo em 2026?", "sell_out"),
        ("Quais CDs estão em ruptura de Extrato?", "estoque"),
        ("Quantas adesões ao PBM tivemos em julho?", "pbm"),
        ("Quais médicos estão no painel do Josias?", "forca_vendas"),
        ("Quantas visitas efetivas fizemos em agosto?", "forca_vendas"),
    ],
)
def test_tema_principal_da_pergunta(pergunta, esperada):
    assert escolher_secoes(pergunta)[0] == esperada


def test_pergunta_que_cruza_areas_leva_os_dois_temas():
    """São frequentes no dia a dia; mandar só um tema esconderia metade das
    regras necessárias."""
    secoes = escolher_secoes(
        "No território do Hermes, quanto prescreveram e quanto foi dispensado em unidades?"
    )

    assert "prescricao" in secoes
    assert "sell_out" in secoes or "forca_vendas" in secoes


def test_seguimento_herda_o_tema_da_pergunta_anterior():
    """"E em agosto?" não tem palavra nenhuma do assunto: quem tinha era a
    pergunta anterior."""
    historico = (
        HistoryMessage(direction="in", text="Quantas unidades vendeu cada representante em julho?"),
        HistoryMessage(direction="out", text="Foram 1.120 unidades."),
    )

    assert escolher_secoes("E em agosto?", historico)[0] == "sell_out"


def test_pergunta_sem_tema_reconhecido_nao_chuta():
    assert escolher_secoes("bom dia, tudo bem?") == ()


def test_no_maximo_tres_temas():
    notas = pontuar("prescrição, venda, estoque, PBM e visitas do representante")

    assert len(notas) == 5
    assert len(escolher_secoes("prescrição, venda, estoque, PBM e visitas do representante")) == 3


# --- montagem do contexto -------------------------------------------------


def test_contexto_recortado_e_muito_menor_que_o_documento(catalogo):
    contexto = montar_contexto_do_plano(catalogo, "Quais CDs estão em ruptura de Extrato?")

    assert contexto.secoes[0] == "estoque"
    assert not contexto.completo
    assert contexto.tokens_estimados < len(catalogo.references_text) // 8


def test_contexto_leva_sempre_as_regras_gerais_e_o_mapa_de_ligacoes(catalogo):
    """Sem o mapa, uma pergunta que cruza áreas não teria como ser
    respondida com a seção de um tema só."""
    contexto = montar_contexto_do_plano(catalogo, "Quais CDs estão em ruptura de Extrato?")

    assert "não invente a resposta" in contexto.texto
    assert "Como os temas se ligam" in contexto.texto
    assert "cddd.forca_vendas" in contexto.texto


def test_os_dois_primeiros_temas_vao_inteiros(catalogo):
    """Pergunta que cruza áreas é frequente. Com o segundo tema resumido, a
    IA pediu o documento inteiro e a segunda chamada custou 44 mil tokens e
    80 segundos (medido em 2026-09-17) — mais caro que mandar a seção."""
    contexto = montar_contexto_do_plano(
        catalogo, "Qual o market share da Ease e quantas visitas a Marta fez em agosto de 2026?"
    )

    assert contexto.secoes[:2] == ("sell_out", "forca_vendas")
    assert "-- B24 ·" in contexto.texto
    assert "-- E22 ·" in contexto.texto


def test_do_terceiro_tema_em_diante_vai_o_resumo(catalogo):
    contexto = montar_contexto_do_plano(
        catalogo,
        "No território do Hermes, quanto prescreveram e quanto foi dispensado em unidades?",
    )

    assert len(contexto.secoes) == 3
    assert "Tema relacionado (resumo)" in contexto.texto
    # Era 20 mil. Subiu em 2026-09-23 com as análises de mercado por classe
    # (B32–B42), que vão completas junto com o Sell Out: ~7 mil tokens a mais,
    # ~US$ 0,012 por pergunta de vendas pelo custo real de set/26. Decisão
    # consciente de custo; se passar disso, o caminho é a seção própria.
    assert contexto.tokens_estimados < 27000


def test_schema_vai_filtrado_pelas_tabelas_do_tema(catalogo):
    contexto = montar_contexto_do_plano(catalogo, "Quais CDs estão em ruptura de Extrato?")

    assert "estoque_redes.vw_forecast_projecao_cd" in contexto.texto
    assert "pbm.fato_pbm_adesoes" not in contexto.texto


def test_sem_tema_reconhecido_vai_so_o_nucleo(catalogo):
    """Sem tema, quase sempre é conversa ("quem é você?"). Mandar o
    documento inteiro custava ~34 mil tokens por um cumprimento — mais caro
    que uma consulta de verdade. Se precisar de dado, a IA pede a seção."""
    contexto = montar_contexto_do_plano(catalogo, "quem é você?")

    assert not contexto.completo
    assert contexto.secoes == ()
    assert "-- A01 ·" not in contexto.texto
    assert "PRECISO DA SEÇÃO" in contexto.texto
    # Era 3 mil. O preâmbulo ganhou em 2026-09-23 o roteiro de raciocínio
    # para pergunta sem consulta pronta (~1,1 mil tokens, ~US$ 0,002 por
    # pergunta): é o único lugar que chega à IA em todo tema.
    assert contexto.tokens_estimados < 3500


def test_segunda_tentativa_pede_o_documento_inteiro(catalogo):
    contexto = montar_contexto_do_plano(
        catalogo, "Quais CDs estão em ruptura de Extrato?", completo=True
    )

    assert contexto.completo
    assert "-- D10 ·" in contexto.texto


def test_contexto_da_resposta_nao_leva_o_documento(catalogo):
    """Quem redige precisa do resultado e das regras de texto, não das
    regras de SQL — é o corte que mais economiza."""
    contexto = montar_contexto_da_resposta(catalogo)

    assert "```sql" not in contexto.texto
    # Era 1,5 mil; subiu com o preâmbulo (ver o teste do núcleo acima).
    assert contexto.tokens_estimados < 2000
    assert "ainda não está disponível" in contexto.texto


def test_filtrar_schema_mantem_o_schema_de_cada_tabela():
    texto = (
        "# Schema\n\n## cddd\n\n- `cddd.pdvs` (tabela): cod_pdv bigint\n"
        "- `cddd.apres` (tabela): cod_apresentacao bigint\n\n## pbm\n\n"
        "- `pbm.fato_pbm_adesoes` (tabela): \"EAN\" text\n"
    )

    filtrado = filtrar_schema(texto, {"cddd.pdvs"})

    assert "## cddd" in filtrado
    assert "cddd.pdvs" in filtrado
    assert "cddd.apres" not in filtrado
    assert "pbm" not in filtrado
