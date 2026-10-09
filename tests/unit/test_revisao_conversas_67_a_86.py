"""Os dez pontos da revisão das conversas 67, 81, 82 e 86 (2026-10-08).

Cada teste parte de um caso real: o rascunho que a ancoragem barrou, a
planilha que disse "nenhuma linha em branco" com médicos fora da base, a
pergunta que custou US$ 0,14 para dizer "pode enviar", o gráfico refeito no
banco só para mudar de cor, o print do gráfico do próprio Jarvis lido como
imagem nova.
"""

import datetime
import io
import json
import logging
from decimal import Decimal

import pytest
from openpyxl import Workbook

from ai_orchestrator import ajuste_grafico, canned, saldo
from ai_orchestrator.grounding import check_grounding_varias
from ai_orchestrator.models import AIReply
from ai_orchestrator.orchestrator import handle_message
from ai_orchestrator.rules import arquivo_a_seguir
from attachments import deposito
from attachments.planilha import ler_estrutura
from attachments.qa import eh_marcador
from catalog.loader import load_catalog
from conversations.models import Conversation
from datasource.executors.fake import FakeQueryExecutor, make_result
from datasource.sql_guard import validate_sql
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, leitura, plano, resposta
from web.views import usuario_json
from whatsapp import graficos, saida

pytestmark = pytest.mark.django_db

UNIDADES = make_result(("sku", "unidades"), [("259434", 47.0), ("259435", 30.0)])
GRAFICO = {"tipo": "barras", "x": "sku", "series": ["unidades"], "titulo": "Unidades"}


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


@pytest.fixture
def conversa(django_user_model):
    user = django_user_model.objects.create_user("ana", password="x")
    return Conversation.objects.create(user=user)


def _pergunta(conversa, texto, client_id="c-1", **anexo):
    return Message.objects.create(
        conversation=conversa,
        direction=Message.Direction.INBOUND,
        content=texto,
        client_message_id=client_id,
        status=Message.Status.RECEIVED,
        **anexo,
    )


def _responder(mensagem, catalogo, provider, executor=None):
    return handle_message(
        mensagem, channel=FakeChannel(), provider=provider,
        executor=executor or FakeQueryExecutor([]), catalog=catalogo,
    )


def _com_grafico(conversa, catalogo, grafico=None):
    provider = ScriptedAIProvider([plano()], [resposta("Foram 47 unidades.", chart=grafico or GRAFICO)])
    reply = _responder(_pergunta(conversa, "unidades por SKU"), catalogo, provider, FakeQueryExecutor([UNIDADES]))
    assert reply.raw_response.get("grafico")
    return reply


def _xlsx(abas) -> bytes:
    livro = Workbook()
    livro.remove(livro.active)
    for titulo, linhas in abas.items():
        aba = livro.create_sheet(titulo)
        for linha in linhas:
            aba.append(list(linha))
    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()


def _com_planilha(conversa, dados, nome, texto, client_id="c-2"):
    return _pergunta(
        conversa, texto, client_id=client_id,
        anexo_tipo=Message.Anexo.PLANILHA, anexo_nome=nome,
        anexo_resumo=ler_estrutura(nome, dados).resumo, anexo_token=deposito.guardar(dados),
    )


# ------------------------------------------------ 1 e 2. ancoragem


def test_explicacao_do_metodo_com_regras_documentadas_passa_na_ancoragem():
    """Conversa 67 #67: a explicação certa da régua de canais virou o texto
    de reserva por causa de "equipes 1, 2 e 4" e "Base 660" — números da
    regra documentada, não dados."""
    rascunho = (
        "PX da FV é o volume prescrito por médicos que estão hoje no painel das equipes 1, 2 e 4. "
        "Digital + Orgânico é o PX dos médicos da auditoria que não aparecem no painel atual, no "
        "histórico de inativos, na Área Médica, no Email MKT ou na Base 660. Visita efetiva exclui o setor 3000."
    )

    assert check_grounding_varias(rascunho, [((), (), "", None)], "como você separa os canais?").ok


def test_ordinal_do_trimestre_nao_e_numero_do_dado():
    """Conversa 67 #49: "no 2º trimestre de 2026" foi barrado pelo "2"."""
    consulta = (("ano", "px"), [(2026, 1500.0)], "", 1)

    assert check_grounding_varias("No 2º trimestre de 2026 foram 1500 prescrições.", [consulta], "px").ok


def test_data_vinda_de_outra_consulta_da_mesma_resposta_tem_fonte():
    """Conversa 67 #35: "carregado em 11/09/2026" veio da consulta de
    reconhecimento (MAX(created_at)), não da principal, e a resposta foi
    barrada. Todas as consultas da resposta sustentam o texto."""
    principal = (("px",), [(1500.0,)], "", 1)
    reconhecimento = (("carga",), [("2026-09-11T10:00:00-03:00",)], "", 1)
    texto = "Foram 1500 prescrições, com a base carregada em 11/09/2026."

    assert not check_grounding_varias(texto, [principal], "px").ok
    assert check_grounding_varias(texto, [principal, reconhecimento], "px").ok


def test_rotulo_nao_vira_brecha_para_numero_inventado():
    assert not check_grounding_varias(
        "As equipes 1, 2 e 4 somam 350 médicos.", [((), (), "", None)], "quantos médicos?"
    ).ok


def test_tabela_crua_mantem_o_grafico_pedido(conversa, catalogo):
    """Conversa 86: a redação reprovada duas vezes caía na tabela crua e o
    gráfico pedido sumia, com os números do banco à mão."""
    provider = ScriptedAIProvider(
        [plano()], [resposta("Foram 52 unidades.", chart=GRAFICO), resposta("Foram 63 unidades.", chart=GRAFICO)]
    )

    reply = _responder(_pergunta(conversa, "unidades por SKU"), catalogo, provider, FakeQueryExecutor([UNIDADES]))

    assert reply.rule == "resposta_sem_narrativa"
    assert reply.raw_response["grafico"]["x"] == "sku"


def test_whatsapp_manda_o_grafico_junto_da_tabela_crua(conversa, catalogo, monkeypatch):
    monkeypatch.setattr(graficos, "png", lambda grafico, dados: b"png" if grafico and dados.get("rows") else None)
    provider = ScriptedAIProvider(
        [plano()], [resposta("Foram 52 unidades.", chart=GRAFICO), resposta("Foram 63 unidades.", chart=GRAFICO)]
    )
    _responder(_pergunta(conversa, "unidades por SKU"), catalogo, provider, FakeQueryExecutor([UNIDADES]))
    enviada = Message.objects.get(direction=Message.Direction.OUTBOUND)

    envios = saida.montar(enviada)

    assert [e.tipo for e in envios].count("imagem") == 1


# ------------------------------------------------ 3, 5 e 6. referências


def test_referencias_de_crescimento_composto_e_px_por_sku_passam_no_validador(catalogo):
    referencias = {r.id: r for r in catalogo.references}

    for ref in ("A23", "A24"):
        assert ref in referencias
        assert validate_sql(referencias[ref].sql, catalogo).approved
    assert "POWER(" in referencias["A23"].sql.upper()
    assert "'011'" in referencias["A24"].sql and "'067'" in referencias["A24"].sql


# ------------------------------------------------ 7. planilha


PEDIDO_DA_PLANILHA = {
    "coluna_chave": "CRM",
    "chave_no_resultado": "crm",
    "colunas": [{"coluna_destino": "Tipo de visita", "valor_no_resultado": "tipo"}],
}
SQL_DA_AREA_MEDICA = (
    "SELECT a.crm_link AS crm, a.tipo_visita_tecnica AS tipo, a.data_cadastro AS atualizado_em "
    "FROM marketing.area_medica_usuarios a"
)


def _planilha_da_area_medica(conversa, catalogo):
    dados = _xlsx({"Planilha1": [("CRM",), ("1",), ("2",), ("3",), ("4",)]})
    resultado = make_result(("crm", "tipo", "atualizado_em"), [
        ("1", "Sim, visita remota", "2026-10-06T05:01:20-03:00"),
        ("2", "Não cadastrado na Área Médica", "2026-10-06T05:01:20-03:00"),
        ("3", "Não cadastrado na Área Médica", "2026-10-06T05:01:20-03:00"),
        ("4", "Não cadastrado na Área Médica", "2026-10-06T05:01:20-03:00"),
    ])
    provider = ScriptedAIProvider(
        [plano(sql=SQL_DA_AREA_MEDICA, preenchimento=PEDIDO_DA_PLANILHA)], [resposta("A coluna nova traz o tipo de visita.")]
    )
    mensagem = _com_planilha(conversa, dados, "painel.xlsx", "inclua o tipo de visita da Área Médica")
    reply = _responder(mensagem, catalogo, provider, FakeQueryExecutor([resultado, resultado]))
    return reply, provider


def test_rodape_diz_quantos_casaram_de_verdade_e_a_data_da_base(conversa, catalogo):
    """Conversa 81: "57 de 57, nenhuma linha ficou em branco", com parte dos
    médicos marcada "Não cadastrado na Área Médica"; e a data da base do
    Marketing, que a consulta trouxe, não foi citada."""
    reply, _ = _planilha_da_area_medica(conversa, catalogo)

    assert "**1 de 4 linhas com o dado do banco**" in reply.reply_text
    assert "3 como “Não cadastrado na Área Médica”" in reply.reply_text
    assert "Base do Marketing atualizada em 06/10/2026." in reply.reply_text
    # O aviso dominante não sai de novo como "valor que domina a coluna".
    assert "aparece em 3 das 4" not in reply.reply_text


def test_redacao_sabe_dos_avisos_e_nao_repete_o_rodape(conversa, catalogo):
    _, provider = _planilha_da_area_medica(conversa, catalogo)

    devolvida = provider.answer_requests[0].planilha_devolvida
    assert "ATENÇÃO: só 1 trazem o dado do banco" in devolvida
    assert "Base do Marketing atualizada em 06/10/2026" in devolvida


def test_marcador_de_ausencia_nao_confunde_resposta_curta():
    assert eh_marcador("Não cadastrado na Área Médica")
    assert eh_marcador("Não informado no cadastro")
    assert eh_marcador("Sem correspondência")
    assert not eh_marcador("Não")
    assert not eh_marcador("Já recebo visitação")


# ------------------------------------------------ 8. custo


def test_aviso_de_arquivo_a_seguir_responde_sem_modelo(conversa, catalogo):
    """Conversa 82 #1: US$ 0,14 para dizer "pode enviar a planilha"."""
    provider = ScriptedAIProvider([], [])
    texto = ("Jarvis.. pegue essa base de dados que será enviada a seguir e cruze as informacoes de "
             "endereço ou CNPJ da farmacia para determinar quais sao os representantes provaveis")

    reply = _responder(_pergunta(conversa, texto), catalogo, provider)

    assert reply.rule == "arquivo_a_seguir"
    assert reply.reply_text == canned.ARQUIVO_A_SEGUIR
    assert provider.plan_requests == [] and reply.calls.count() == 0


@pytest.mark.parametrize("texto", [
    "Vou enviar essa planilha para a diretoria, me dê o PX de setembro",
    "monte a tabela a seguir com PX por mês",
    "qual o PX de setembro?",
])
def test_pergunta_comum_nao_vira_aviso_de_arquivo(texto):
    assert arquivo_a_seguir(texto) is None


def test_mensagem_com_o_anexo_nao_cai_no_aviso(conversa, catalogo):
    dados = _xlsx({"Dados": [("Rede",), ("Pague Menos",)]})
    provider = ScriptedAIProvider([plano(intent="conversation", sql="", user_message="Recebi.")], [])
    mensagem = _com_planilha(conversa, dados, "base.xlsx", "a base vai em seguida, já está aqui")

    reply = _responder(mensagem, catalogo, provider)

    assert reply.rule != "arquivo_a_seguir"


def test_cor_do_rotulo_pelo_sinal_sem_consulta_nem_modelo(conversa, catalogo):
    """Conversa 86 #12: "verde quando sobe e vermelho quando desce" refez a
    consulta e a redação (US$ 0,03) para pintar números que já estavam na tela."""
    _com_grafico(conversa, catalogo)
    provider, executor = ScriptedAIProvider([], []), FakeQueryExecutor()

    reply = _responder(
        _pergunta(conversa, "Mude a cor do rotulo de Dados p/ ver quando sobe e vermelho quando desce", "c-9"),
        catalogo, provider, executor,
    )

    assert reply.rule == "ajuste_de_grafico"
    assert reply.raw_response["grafico"]["cores_por_sinal"] == "rotulo"
    assert reply.raw_response["grafico"]["x"] == "sku"
    assert provider.plan_requests == [] and executor.executed == []


def test_cor_por_sinal_na_especificacao_vega():
    spec = {"mark": "bar", "encoding": {
        "x": {"field": "serie", "type": "nominal"},
        "y": {"field": "crescimento_pct", "type": "quantitative"},
    }}

    novo = ajuste_grafico.aplicar_no_vega(spec, {"cores_por_sinal": "rotulo", "rotulos": True})

    texto = [c for c in novo["layer"] if ajuste_grafico._marca(c) == "text"][0]
    assert texto["encoding"]["text"]["field"] == "crescimento_pct"
    assert texto["encoding"]["color"]["condition"]["value"] == ajuste_grafico.VERMELHO
    assert 'datum["crescimento_pct"] < 0' == texto["encoding"]["color"]["condition"]["test"]
    assert spec == {"mark": "bar", "encoding": spec["encoding"]}       # o original fica intacto


def test_vega_composto_ou_com_series_vai_para_a_ia():
    assert ajuste_grafico.aplicar_no_vega({"facet": {"field": "a"}, "spec": {"mark": "bar"}}, {"rotulos": True}) is None
    com_series = {"mark": "bar", "encoding": {
        "x": {"field": "mes", "type": "ordinal"}, "y": {"field": "px", "type": "quantitative"},
        "color": {"field": "canal", "type": "nominal"},
    }}
    assert ajuste_grafico.aplicar_no_vega(com_series, {"cor": ajuste_grafico.VERDE}) is None


def test_ajuste_de_cor_num_grafico_vega_da_conversa(conversa, catalogo):
    vega = {"tipo": "nenhum", "x": "", "series": [], "titulo": "Unidades", "vega_lite": json.dumps({
        "mark": "bar", "encoding": {
            "x": {"field": "sku", "type": "nominal"}, "y": {"field": "unidades", "type": "quantitative"},
        }})}
    _com_grafico(conversa, catalogo, vega)
    provider = ScriptedAIProvider([], [])

    reply = _responder(_pergunta(conversa, "pinta as barras de azul", "c-9"), catalogo, provider)

    assert reply.rule == "ajuste_de_grafico"
    camadas = reply.raw_response["grafico"]["vega"]["layer"]
    assert camadas[0]["mark"]["color"] == "#5558D4"


def test_mudanca_de_dado_continua_com_a_ia():
    """86 #11 trocou a série mensal por uma barra por canal: é outro dado."""
    assert ajuste_grafico.ler_ajuste(
        "Quero um gráfico de barra, sendo cada barra um modal (Digital + Organico, Mercado Cannabis, "
        "Visitados pela FV em 2026)"
    ) is None


def test_whatsapp_desenha_a_cor_por_sinal():
    spec = graficos.de_simples({**GRAFICO, "cores_por_sinal": "rotulo"},
                               {"columns": ["sku", "unidades"], "rows": [["a", 3.0], ["b", -2.0]]})

    textos = [c for c in spec["layer"] if ajuste_grafico._marca(c) == "text"]
    assert textos and "condition" in textos[0]["encoding"]["color"]
    assert spec["data"]["values"]


# ------------------------------------------------ 9. saldo da OpenAI


@pytest.fixture
def credito(monkeypatch):
    monkeypatch.setenv(saldo.VARIAVEL_CREDITO, "100")
    monkeypatch.setenv(saldo.VARIAVEL_DATA, "2026-10-01")
    monkeypatch.delenv(saldo.VARIAVEL_LIMIAR, raising=False)
    return monkeypatch


def test_sem_saldo_informado_nao_ha_aviso(monkeypatch):
    monkeypatch.delenv(saldo.VARIAVEL_CREDITO, raising=False)
    assert saldo.estimativa() is None and saldo.aviso() == ""


def test_saldo_folgado_nao_avisa(credito):
    credito.setattr(saldo, "_gasto", lambda desde: Decimal("10") if desde.date() == datetime.date(2026, 10, 1) else Decimal("0.7"))
    assert saldo.aviso() == ""


def test_saldo_abaixo_do_limiar_avisa(credito):
    credito.setattr(saldo, "_gasto", lambda desde: Decimal("85"))

    texto = saldo.aviso()

    assert "US$ 15.00" in texto and "OPENAI_CREDITO_USD" in texto


def test_saldo_que_acaba_em_poucos_dias_avisa_antes_do_limiar(credito):
    # Gastou 40 desde a recarga; 35 na última semana = US$ 5/dia, 60 restantes.
    credito.setattr(saldo, "_gasto", lambda desde: Decimal("40") if desde.date() == datetime.date(2026, 10, 1) else Decimal("35"))
    credito.setenv(saldo.VARIAVEL_LIMIAR, "10")

    assert saldo.estimativa()["dias_restantes"] == 12
    assert saldo.aviso() == ""
    credito.setattr(saldo, "_gasto", lambda desde: Decimal("80") if desde.date() == datetime.date(2026, 10, 1) else Decimal("35"))
    assert "acaba em 4 dias" in saldo.aviso()


def test_aviso_de_saldo_so_para_a_equipe(credito, django_user_model):
    credito.setattr(saldo, "_gasto", lambda desde: Decimal("95"))
    equipe = django_user_model.objects.create_user("bi", password="x", is_staff=True)
    pessoa = django_user_model.objects.create_user("rep", password="x")

    assert usuario_json(equipe)["aviso_saldo"].startswith("Saldo estimado da OpenAI")
    assert usuario_json(pessoa)["aviso_saldo"] == ""


def test_log_do_saldo_sai_uma_vez_por_dia(credito, caplog):
    from django.core.cache import cache

    cache.clear()
    credito.setattr(saldo, "_gasto", lambda desde: Decimal("95"))
    with caplog.at_level(logging.ERROR, logger="ai_orchestrator.saldo"):
        saldo.registrar_se_preciso()
        saldo.registrar_se_preciso()

    assert len([r for r in caplog.records if "Saldo estimado" in r.getMessage()]) == 1


# ------------------------------------------------ 10. arquivo e print do Jarvis


DEVOLVIDA = _xlsx({
    "Worksheet": [("CNPJ", "Representante"), ("1", "Ana")],
    "Resumo por representante": [("Representante", "PDVs"), ("Ana", 1)],
    "Notas do Jarvis": [("Onde", "O quê"), ("Aba Worksheet", "coluna nova")],
})


def test_arquivo_devolvido_pelo_jarvis_sem_pedido_pergunta_o_que_fazer(conversa, catalogo):
    """Conversa 82 #3: "Segue o arquivo." com a planilha que o próprio Jarvis
    devolveu custou US$ 0,11 para descrever as abas e perguntar o que fazer."""
    provider = ScriptedAIProvider([], [])
    mensagem = _com_planilha(conversa, DEVOLVIDA, "balcao - Dados brutos.xlsx", "Segue o arquivo.")

    reply = _responder(mensagem, catalogo, provider)

    assert reply.rule == "arquivo_do_jarvis"
    assert reply.decision == AIReply.Decision.CLARIFY
    assert "`Worksheet`, `Resumo por representante`" in reply.reply_text
    assert provider.plan_requests == [] and reply.calls.count() == 0


def test_arquivo_do_jarvis_com_pedido_segue_para_a_ia(conversa, catalogo):
    provider = ScriptedAIProvider([plano(intent="conversation", sql="", user_message="Vou atualizar.")], [])
    mensagem = _com_planilha(conversa, DEVOLVIDA, "balcao.xlsx", "atualize os representantes com o cadastro de hoje")

    reply = _responder(mensagem, catalogo, provider)

    assert reply.rule != "arquivo_do_jarvis"
    assert len(provider.plan_requests) == 1


def _print(conversa, texto, client_id="c-9"):
    return _pergunta(conversa, texto, client_id=client_id, anexo_tipo=Message.Anexo.IMAGEM,
                     anexo_nome="print-colado.png", anexo_resumo="imagem", anexo_token=deposito.guardar(b"\x89PNG"))


def test_print_do_grafico_do_jarvis_com_pedido_vai_direto_para_a_consulta(conversa, catalogo):
    """Conversa 67 #61: "Retire o Isolado 20 deste gráfico" com o print do
    gráfico do Jarvis foi lido como imagem nova ("removeria a série
    vermelha"), e a pessoa teve de responder "Isso. Faça isso"."""
    _com_grafico(conversa, catalogo)
    provider = ScriptedAIProvider([plano()], [resposta("Foram 47 unidades.")])
    mensagem = _print(conversa, "Retire o Isolado 20 deste gráfico")
    token = mensagem.anexo_token

    _responder(mensagem, catalogo, provider, FakeQueryExecutor([UNIDADES]))

    assert provider.image_requests == []
    assert "gráfico da sua resposta anterior" in provider.plan_requests[0].question
    assert deposito.buscar(token) is None


def test_print_sem_grafico_do_jarvis_na_conversa_continua_sendo_lido(conversa, catalogo):
    provider = ScriptedAIProvider(leituras=[leitura("O gráfico mostra três séries.")])

    _responder(_print(conversa, "Retire o Isolado 20 deste gráfico", "c-1"), catalogo, provider)

    assert len(provider.image_requests) == 1
