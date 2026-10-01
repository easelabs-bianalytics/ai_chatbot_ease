"""Ancoragem numérica (ADR-0010).

Uma resposta de BI com número inventado é pior do que nenhuma resposta: ela
vira slide, e-mail e decisão. Esta é a última barreira antes do envio.
"""

from ai_orchestrator.grounding import check_grounding

COLUNAS = ("cod_apresentacao", "unidades")
LINHAS = (("259434", 47.0), ("234194", 5.0))
PERGUNTA = "unidades por SKU em agosto de 2026"
SQL = "SELECT cod_apresentacao, SUM(und) FROM cddd.vendas_consolidado WHERE cod_anomes >= '2026-08-01' GROUP BY 1"


def _checar(resposta, colunas=COLUNAS, linhas=LINHAS, pergunta=PERGUNTA, sql=SQL):
    return check_grounding(resposta, colunas, linhas, pergunta, sql)


def test_numero_que_veio_do_banco_passa():
    assert _checar("O Extrato teve 47 unidades.").ok


def test_numero_inventado_e_reprovado():
    """O caso que motiva a regra: o modelo completa com um número plausível."""
    resultado = _checar("O Extrato teve 52 unidades.")

    assert not resultado.ok
    assert resultado.unsupported == ("52",)
    assert "não está no resultado" in resultado.reason


def test_soma_feita_pelo_modelo_e_reprovada():
    """47 + 5 = 52 está certo, e mesmo assim não passa: se o total importa,
    ele tem de vir da consulta (ADR-0010)."""
    assert not _checar("No total foram 52 unidades.").ok


def test_arredondamento_do_valor_do_banco_passa():
    assert _checar("Crescimento de 1,35.", linhas=(("crescimento", 1.3512),)).ok


def test_formato_brasileiro_e_reconhecido():
    assert _checar("Foram 1.234,5 unidades.", linhas=(("total", 1234.5),)).ok


def test_numero_da_pergunta_passa():
    """O ano veio de quem perguntou; repetir não é inventar."""
    assert _checar("Em 2026 o Extrato teve 47 unidades.").ok


def test_numero_dentro_de_texto_do_resultado_passa():
    """SKU, EAN e CNPJ voltam como texto, e a resposta cita eles."""
    assert _checar("O SKU 259434 teve 47 unidades.").ok


def test_quantidade_de_linhas_passa():
    """"São 2 SKUs" é fato do resultado, não conta inventada."""
    assert _checar("São 2 SKUs no período.").ok


def test_competencia_aaaamm_sustenta_o_mes_e_o_ano():
    """O mercado devolve a competência como '202509' e a resposta escreve
    "set/2025". Reprovar isso derrubou duas respostas certas (2026-09-23)."""
    assert _checar(
        "De set/2025 a ago/2026, o share foi de 16,65% a 14,65%.",
        colunas=("cod_anomes", "share"),
        linhas=(("202509", 16.65), ("202608", 14.65)),
        pergunta="share nos últimos 12 meses",
        sql="SELECT cod_anomes, 1 FROM td.fato_td GROUP BY 1",
    ).ok


def test_mat_sustenta_os_12_meses():
    """MAT é 12 meses por definição; fora do assunto MAT, 12 precisa de fonte."""
    assert _checar("O MAT são os 12 meses fechados.", pergunta="qual MAT você usou?").ok
    assert not _checar("Foram 12 unidades.", pergunta="unidades em agosto").ok


def test_codigo_de_seis_digitos_nao_vira_ano():
    """SKU 259434 não é competência (mês 34): não sustenta um '2594'."""
    assert not _checar("Foram 2594 unidades.").ok


def test_literal_do_filtro_passa():
    assert _checar(
        "Em 2026-08-01 em diante, 47 unidades.",
    ).ok


def test_literal_do_select_nao_ancora_numero():
    """Senão bastaria o modelo escrever o número que quisesse dentro da
    própria consulta para dar suporte à resposta."""
    resultado = check_grounding(
        "O total é 999.",
        ("total",),
        (),
        "qual o total?",
        "SELECT 999 AS total FROM cddd.vendas_consolidado",
    )

    assert not resultado.ok


def test_razao_apresentada_como_percentual_e_reprovada():
    """"Cresc_%" é razão (1,35), não percentual. Converter para "35%" é
    justamente a leitura errada que o catálogo avisa — e o número 35 não
    existe no resultado."""
    assert not _checar("Crescimento de 35%.", linhas=(("cresc", 1.35),)).ok


def test_resposta_sem_numero_nenhum_passa():
    assert _checar("Não houve movimento relevante no período.").ok


# O caso real de 2026-09-21: "Porque a Ease Labs caiu em Sell Out em jul/26?".
# A análise estava certa e foi reprovada duas vezes porque citava as quedas
# sem o sinal de menos; a pessoa recebeu a tabela crua.
LINHAS_DA_QUEDA = (
    ("Total Ease Labs", 7233.0, 7720.0, 487.0, 6.7),
    ("Vendas extras", 456.0, 395.0, -61.0, -13.4),
    ("Voucher", -234.87999999999982, -246.50999999999985, -11.630000000000024, 5.0),
)


def test_queda_citada_sem_sinal_passa():
    texto = "Vendas extras recuaram 61 unidades (13,4%)."

    assert _checar(texto, linhas=LINHAS_DA_QUEDA).ok


def test_valor_negativo_com_ruido_de_ponto_flutuante_arredondado_passa():
    texto = "O voucher foi de 234,88 para 246,51, uma diferença de 11,63."

    assert _checar(texto, linhas=LINHAS_DA_QUEDA).ok


def test_valor_absoluto_nao_abre_brecha_para_numero_inventado():
    assert not _checar("Vendas extras recuaram 62 unidades.", linhas=LINHAS_DA_QUEDA).ok


# ------------------------------------------- explicação de planilha (2026-10-01)
# Racional Metas 2T26: a explicação certa da meta do Hermes foi reprovada
# duas vezes e virou tabela crua. Nenhum dos três casos abaixo é número novo.


def test_arredondamento_com_milhar_vale():
    """8634,52 dito como "8.635 unidades": o ponto é milhar, não decimal."""
    assert check_grounding("Meta total de aproximadamente 8.635 unidades.", ("meta",), ((8634.518498,),), "", "").ok


def test_fracao_dita_em_percentual_vale():
    assert check_grounding("A participação dele é de 6,60%.", ("part",), ((0.0659568115,),), "", "").ok


def test_numeracao_de_lista_nao_e_dado():
    texto = "Passo a passo:\n1. Meta do 1T: 515 unidades.\n2. Participação: 6,60%.\n3. Resultado: 569,51."
    assert check_grounding(texto, ("a", "b", "c"), ((515, 0.0659568, 569.5053),), "", "").ok


def test_mesmo_numero_com_menos_casas_vale():
    assert check_grounding("participação registrada de 0,0659568115", ("p",), ((0.06595681152099932,),), "", "").ok


def test_diferenca_calculada_no_texto_continua_barrada():
    """569,51 − 561,51 = 8: conta feita pelo modelo, fora do resultado."""
    resultado = check_grounding("A diferença é de 8 unidades.", ("calc", "gravado"), ((569.505, 561.505),), "", "")
    assert not resultado.ok and "8" in resultado.unsupported


def test_percentual_inventado_continua_barrado():
    """0,0659 é 6,6%, não 7,5%: a conversão de unidade não abre a porta."""
    assert not check_grounding("A participação é de 7,5%.", ("p",), ((0.0659568,),), "", "").ok


def test_milhar_errado_continua_barrado():
    assert not check_grounding("Meta de 8.700 unidades.", ("meta",), ((8634.52,),), "", "").ok


def test_numero_em_escala_vale():
    """"28,6 mil unidades" a partir de 28.606,8 (planilha de metas)."""
    assert check_grounding("São cerca de 28,6 mil unidades.", ("t",), ((28606.776,),), "", "").ok
    assert check_grounding("Meta de 12,1 milhões.", ("t",), ((12128300.52,),), "", "").ok


def test_escala_inventada_continua_barrada():
    assert not check_grounding("São cerca de 31 mil unidades.", ("t",), ((28606.776,),), "", "").ok
