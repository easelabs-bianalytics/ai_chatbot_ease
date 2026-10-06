"""Leitura do evento da Evolution e formato do texto no WhatsApp (ADR-0028).

O incidente que isto previne é o da referência (2026-09-04): um número
conectado respondeu em dois grupos reais. Aqui o que se fixa é a leitura —
grupo, menção, eco do próprio Jarvis, número escondido atrás de @lid — e a
forma do texto no celular.
"""

import pytest

from whatsapp import entrada, formato, graficos


def _evento(message, remote="5511999998888@s.whatsapp.net", **chave):
    return {"event": "messages.upsert", "instance": "jarvis", "data": {
        "key": {"remoteJid": remote, "fromMe": False, "id": "ABC1", **chave},
        "pushName": "Paulo", "message": message,
    }}


def test_texto_individual():
    r = entrada.ler(_evento({"conversation": "vendas de agosto"}))

    assert (r.tipo, r.texto, r.grupo, r.numero, r.nome) == ("texto", "vendas de agosto", False, "5511999998888", "Paulo")


@pytest.mark.parametrize("payload", [
    {"event": "connection.update", "data": {}},
    _evento({"conversation": "eco"}, fromMe=True),
    _evento({"conversation": "status"}, remote="status@broadcast"),
    _evento({"stickerMessage": {}}),
    None,
])
def test_o_que_nao_e_pergunta_nao_e_lido(payload):
    """fromMe é o eco do que o próprio Jarvis mandou: processá-lo faria o
    Jarvis responder a si mesmo."""
    assert entrada.ler(payload) is None


def test_grupo_com_mencao_e_numero_escondido_atras_de_lid():
    """O WhatsApp esconde o número em parte dos grupos (@lid); a Evolution
    manda o número de verdade em `participantAlt`."""
    r = entrada.ler(_evento(
        {"extendedTextMessage": {"text": "@5511900001111 vendas de agosto",
                                 "contextInfo": {"mentionedJid": ["5511900001111@s.whatsapp.net"]}}},
        remote="120363000000@g.us", participant="9988776655@lid", participantAlt="5511977776666@s.whatsapp.net",
    ))

    assert r.grupo and r.numero == "5511977776666"
    assert entrada.marcou_o_jarvis(r, "5511900001111")
    assert not entrada.marcou_o_jarvis(r, "5511900002222")
    assert entrada.sem_mencao(r.texto, "5511900001111") == "vendas de agosto"


def test_mencao_pelo_lid_e_pelo_nome_escrito():
    pelo_lid = entrada.ler(_evento(
        {"extendedTextMessage": {"text": "@123 oi", "contextInfo": {"mentionedJid": ["123@lid"]}}},
        remote="1203@g.us", participant="5511@s.whatsapp.net",
    ))
    escrito = entrada.ler(_evento({"conversation": "@Jarvis quanto vendemos?"}, remote="1203@g.us"))

    assert entrada.marcou_o_jarvis(pelo_lid, "", lid_do_jarvis="123@lid")
    assert entrada.marcou_o_jarvis(escrito, "")
    assert entrada.sem_mencao(escrito.texto, "") == "quanto vendemos?"


def test_reacao_documento_imagem_e_audio():
    reacao = entrada.ler(_evento({"reactionMessage": {"text": "👎", "key": {"id": "OUT9"}}}))
    documento = entrada.ler(_evento({"documentWithCaptionMessage": {"message": {"documentMessage": {
        "fileName": "redes.xlsx", "mimetype": "application/vnd.ms-excel", "caption": "preencha"}}}}))
    imagem = entrada.ler(_evento({"imageMessage": {"caption": "o que diz?", "mimetype": "image/jpeg"}}))
    audio = entrada.ler(_evento({"audioMessage": {}}))

    assert (reacao.tipo, reacao.reacao, reacao.reacao_alvo) == ("reacao", "👎", "OUT9")
    assert (documento.tipo, documento.arquivo_nome, documento.texto) == ("documento", "redes.xlsx", "preencha")
    assert (imagem.tipo, imagem.texto) == ("imagem", "o que diz?")
    assert audio.tipo == "audio"


def test_resposta_citando_guarda_a_mensagem_citada():
    r = entrada.ler(_evento({"extendedTextMessage": {"text": "e em julho?", "contextInfo": {
        "stanzaId": "OUT7", "participant": "5511900001111@s.whatsapp.net"}}}, remote="1203@g.us"))

    assert r.citada_id == "OUT7"


# ------------------------------------------------------------ formato


def test_markdown_vira_marcacao_do_whatsapp():
    texto = "## Vendas\n\nForam **4.306 unidades** em ago/2026.\n\n- CDD: 3.100\n- ~~Voucher~~"

    assert formato.de_markdown(texto) == "*Vendas*\n\nForam *4.306 unidades* em ago/2026.\n\n• CDD: 3.100\n• ~Voucher~"


def test_tabela_estreita_vai_em_bloco_e_larga_vira_lista():
    estreita = formato.tabela(["mes", "und"], [["2026-07", 761], ["2026-08", 777.5]])
    larga = formato.tabela(["rede", "representante", "unidades"], [["Pague Menos Nordeste", "Fulano de Tal", 1234]])

    assert estreita.startswith("```") and "777,5" in estreita
    assert larga == "• *Pague Menos Nordeste* — representante: Fulano de Tal · unidades: 1.234"


TABELA_CRUA = (
    "mes | faturamento_ease_td | faturamento_mercado_td | market_share_pct | variacao_faturamento_ease"
    " | variacao_faturamento_ease_pct | variacao_share_pp\n"
    "2026-04-01 | 140.887,61 | 1.336.807,64 | 10,54% |  |  | \n"
    "2026-08-01 | 126.202,3 | 1.545.042,39 | 8,17% | -14.685,31 | -10,4% | -2,37%"
)


def test_tabela_crua_larga_vira_um_registro_por_vez_sem_barras():
    """2026-10-06: a saída de segurança (redação reprovada duas vezes)
    chegou ao WhatsApp como bloco monoespaçado de nove colunas separadas por
    "|", quebrado no meio e ilegível. Larga assim, é um registro por vez,
    uma coluna por linha; célula vazia não aparece."""
    texto = formato.tabela_crua(TABELA_CRUA)

    assert "|" not in texto and "```" not in texto
    abril, agosto = texto.split("\n\n")
    assert abril == ("*01/04/2026*\n  faturamento ease td: 140.887,61\n"
                     "  faturamento mercado td: 1.336.807,64\n  market share pct: 10,54%")
    assert agosto.startswith("*01/08/2026*\n") and "  variacao share pp: -2,37%" in agosto


def test_data_do_banco_sai_como_na_tela():
    """A tela mostra 01/04/2026 (e a hora, quando há); o WhatsApp mostrava
    2026-04-01. Mês sem dia ("2026-07") continua como está."""
    texto = formato.tabela(["dia", "und"], [["2026-04-01", 1], ["2026-10-01T15:46:41-03:00", 2], ["2026-07", 3]])

    assert "01/04/2026" in texto and "01/10/2026 15:46" in texto and "2026-07" in texto


def test_italico_do_markdown_nao_vira_negrito_no_whatsapp():
    """`*assim*` é itálico no Markdown (e na tela); no WhatsApp `*` é negrito."""
    texto = formato.de_markdown("Foram **777** unidades (*dado até 29/09*).\n* item *destaque* fim")

    assert texto == "Foram *777* unidades (_dado até 29/09_).\n• item _destaque_ fim"


def test_negrito_dentro_da_tabela_nao_deixa_asterisco_no_bloco():
    texto = formato.de_markdown("| uf | und |\n|---|---|\n| **SP** | 10 |")

    assert texto == "```\nuf  und\n--  ---\nSP   10\n```"


def test_tabela_crua_estreita_vai_em_bloco_alinhado_e_leva_o_rodape():
    texto = formato.tabela_crua("uf | total\nSP | 10\nRJ | 5\n\n(Mostrando as 2 primeiras de 27 linhas.)")

    assert texto == "```\nuf  total\n--  -----\nSP     10\nRJ      5\n```\n\n_Mostrando as 2 primeiras de 27 linhas._"


def test_tabela_markdown_no_texto_segue_a_largura_do_celular():
    """Tabela que a redação escreve no texto: nunca mais "a | b | c" cru."""
    larga = formato.de_markdown("Veja:\n\n| rede | representante | unidades |\n|---|---|---|\n"
                                "| Pague Menos Nordeste | Fulano de Tal | 1.234 |")

    assert larga == "Veja:\n\n• *Pague Menos Nordeste* — representante: Fulano de Tal · unidades: 1.234"


def test_texto_longo_sai_em_partes_cortadas_no_paragrafo():
    paragrafo = "x" * 2000
    partes = formato.dividir(f"{paragrafo}\n\n{paragrafo}")

    assert partes == [paragrafo, paragrafo]


# ------------------------------------------------------------ gráfico


CATEGORIAS = {"columns": ["competencia", "categoria", "px"],
              "rows": [["2026-01-01", 1, 520.0], ["2026-01-01", 3, 221.0], ["2026-02-01", 1, 617.0],
                       ["2026-02-01", 3, 257.0]]}


def test_formato_simples_vira_vega_lite_com_categoria_legivel():
    """O mesmo ajuste da tela: categoria em número vira "Categoria 1", e
    separar vira um gráfico por categoria na mesma escala."""
    spec = graficos.de_simples({"tipo": "barras", "x": "competencia", "series": ["px"],
                                "grupo": "categoria", "separar": True}, CATEGORIAS)

    assert {"calculate": "'Categoria ' + datum['categoria']", "as": "_grupo"} in spec["transform"]
    assert spec["facet"]["field"] == "_grupo"
    assert spec["resolve"] == {"scale": {"y": "shared"}}


def test_grafico_vira_png_com_os_dados_do_banco():
    imagem = graficos.png({"tipo": "linha", "x": "competencia", "series": ["px"], "grupo": "categoria",
                           "titulo": "PX"}, CATEGORIAS)

    assert imagem[:4] == b"\x89PNG"


def test_especificacao_vega_recebe_os_dados_aqui_e_nao_busca_nada_fora():
    spec = graficos.de_vega({"tipo": "vega", "vega": {"mark": "point", "encoding": {
        "x": {"field": "competencia", "type": "temporal"}, "y": {"field": "px", "type": "quantitative"}}}},
        CATEGORIAS)

    assert spec["data"]["values"][0] == {"competencia": "2026-01-01T12:00:00", "categoria": 1, "px": 520.0}


def test_muitas_categorias_no_png_viram_as_maiores_e_outras():
    """A mesma regra da tela: 30 especialidades em 30 cores não se leem."""
    dados = {"columns": ["mes", "especialidade", "px"],
             "rows": [["2026-01-01", f"E{n:02d}", float(n)] for n in range(30)]}

    agrupado = graficos.de_simples({"tipo": "barras", "x": "mes", "series": ["px"], "grupo": "especialidade"}, dados)
    separado = graficos.de_simples({"tipo": "barras", "x": "mes", "series": ["px"], "grupo": "especialidade",
                                    "separar": True}, dados)

    categorias = {r["especialidade"] for r in agrupado["data"]["values"]}
    assert len(categorias) == 7 and "Outras" in categorias
    assert "somadas em Outras" in agrupado["title"]["subtitle"]
    assert len({r["especialidade"] for r in separado["data"]["values"]}) == 9


def test_formas_do_numero_com_e_sem_o_nono_digito():
    from whatsapp.entrada import formas_do_numero

    assert formas_do_numero("+55 (31) 99005-4127") == {"5531990054127", "553190054127"}
    assert formas_do_numero("553190054127") == {"553190054127", "5531990054127"}
    # fixo (começa com 2 a 5) e número de fora não ganham o 9
    assert formas_do_numero("553132221234") == {"553132221234"}
    assert formas_do_numero("14155550123") == {"14155550123"}


def test_legenda_da_planilha_cortada_avisa_mesmo_com_titulo():
    """No WhatsApp, a tabela com título perdia o aviso de corte (2026-09-30)."""
    from whatsapp.saida import _legenda

    assert "passou de 50.000 linhas" in _legenda(50_000, cortada=True, titulo="PDVs visitados")
    assert _legenda(50_000, cortada=True, titulo="PDVs visitados").startswith("PDVs visitados")
    assert _legenda(340) == "340 linhas"
