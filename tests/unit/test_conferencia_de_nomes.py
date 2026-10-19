"""Conferência dos filtros de nome contra o cadastro (conversa 118, 2026-10-19).

O diretor escreveu "cuibá"; a IA filtrou `pdvs.cidade ILIKE '%CUIBA%'`, que
pega CARAPICUIBA (SP), e a resposta deu os números de Carapicuíba como os de
Cuiabá — sem erro nenhum. Cada teste aqui é uma forma de um nome digitado
virar o número de outra cidade ou de outro representante.
"""

import pytest

from ai_orchestrator.models import AIReply
from ai_orchestrator.orchestrator import handle_message
from catalog.loader import load_catalog
from conversations.models import Conversation
from datasource.conferencia_de_nomes import NomeConferido, conferir, filtros
from datasource.executors.fake import FakeQueryExecutor, make_result
from datasource.models import QueryRun
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta

CIDADE = NomeConferido(tabela="cddd.pdvs", coluna="cidade", uf="uf", rotulo="cidade")
REPRESENTANTE = NomeConferido(tabela="cddd.forca_vendas", coluna="desc_territorio", rotulo="representante")
CONFERIDOS = (CIDADE, REPRESENTANTE)

CADASTRO = {
    "cddd.pdvs.cidade": [("CUIABA", "MT"), ("CARAPICUIBA", "SP"), ("VICOSA", "MG"), ("VICOSA", "AL"),
                         ("RIBEIRAO PRETO", "SP")],
    "cddd.forca_vendas.desc_territorio": [("CARLOS BATISTA",), ("CARLOS PEREIRA",), ("HERMES BIZZOTO",),
                                          ("CAROLINE CARNIEL\t",)],
}

BASE = ("SELECT SUM(fc.und / 1000.0) FROM cddd.fato_cdd fc "
        "LEFT JOIN cddd.pdvs pdvs ON pdvs.cod_pdv = fc.cod_pdv::bigint WHERE ")
REP = "SELECT cod_utc FROM cddd.forca_vendas fv WHERE "


def _conferir(sql):
    return conferir(sql, CONFERIDOS, FakeQueryExecutor(cadastro=CADASTRO))


def test_pedaco_dentro_de_outro_nome_e_recusado_com_o_nome_certo():
    """O caso do diretor: '%CUIBA%' só pega CARAPICUIBA, e o nome parecido
    com o que ele escreveu é CUIABA. A recusa diz os dois."""
    motivo = _conferir(BASE + "pdvs.cidade ILIKE '%CUIBA%'")

    assert "CARAPICUIBA (SP)" in motivo
    assert "CUIABA (MT)" in motivo


def test_pedaco_que_pega_so_a_cidade_pedida_passa():
    """A conversa 119, a certa: '%CUIAB%' só pega CUIABA."""
    assert _conferir(BASE + "pdvs.cidade ILIKE '%CUIAB%'") == ""


def test_pedaco_unico_sem_nome_parecido_passa():
    """'%RIBEIRAO PRET%' pega um nome só, maior que o escrito, mas nenhum
    outro nome é parecido: não há por que recusar."""
    assert _conferir(BASE + "pdvs.cidade ILIKE '%RIBEIRAO PRET%'") == ""


def test_nome_com_acento_ou_minusculas_que_nao_casa_traz_sugestao():
    """O cadastro é em maiúsculas e sem acento: 'CUIABÁ' e = 'Cuiaba' não
    pegam nada, e a consulta voltaria vazia ou com "não houve venda"."""
    for filtro in ("pdvs.cidade ILIKE '%CUIABÁ%'", "pdvs.cidade = 'Cuiaba'"):
        motivo = _conferir(BASE + filtro)
        assert "não pega nenhuma cidade" in motivo
        assert "CUIABA (MT)" in motivo


def test_pedaco_que_pega_varios_representantes_e_recusado():
    """'%CARLOS%' somaria dois representantes: a correção escolhe ou pergunta."""
    motivo = _conferir(REP + "fv.desc_territorio ILIKE '%CARLOS%'")

    assert "2 representantes diferentes" in motivo
    assert "CARLOS BATISTA" in motivo and "CARLOS PEREIRA" in motivo


def test_lista_explicita_com_nomes_exatos_passa():
    """Mais de um nome de propósito, escrito com os nomes do cadastro: é a
    saída que a recusa oferece, e não pode ser recusada de novo."""
    assert _conferir(REP + "fv.desc_territorio IN ('CARLOS BATISTA', 'CARLOS PEREIRA')") == ""


def test_cidade_de_nome_repetido_exige_a_uf():
    """Viçosa existe em MG e em AL: sem a UF, o número soma as duas."""
    motivo = _conferir(BASE + "pdvs.cidade = 'VICOSA'")
    assert "2 UFs" in motivo

    assert _conferir(BASE + "pdvs.cidade = 'VICOSA' AND pdvs.uf = 'MG'") == ""


def test_uf_filtrada_restringe_os_nomes():
    """Com a UF fixa, só contam as cidades dela: '%VICOSA%' em MG é uma
    cidade só, não duas."""
    assert _conferir(BASE + "pdvs.cidade ILIKE '%VICOSA%' AND pdvs.uf = 'MG'") == ""
    assert "não pega nenhuma cidade" in _conferir(BASE + "pdvs.cidade = 'CUIABA' AND pdvs.uf = 'SP'")


def test_espaco_sobrando_no_cadastro():
    """`desc_territorio` tem tab no fim de alguns nomes: = sem TRIM não pega
    nada; com TRIM, pega."""
    assert "TRIM" in _conferir(REP + "fv.desc_territorio = 'CAROLINE CARNIEL'")
    assert _conferir(REP + "TRIM(fv.desc_territorio) = 'CAROLINE CARNIEL'") == ""


def test_filtro_negado_e_coluna_de_outra_tabela_nao_sao_conferidos():
    """NOT ILIKE exclui, não escolhe; e `cidade` de outra tabela não é a do
    cadastro de PDVs."""
    assert filtros(BASE + "pdvs.cidade NOT ILIKE '%CUIBA%'", CONFERIDOS) == []
    assert filtros("SELECT 1 FROM audit.medico m WHERE m.cidade ILIKE '%CUIBA%'", CONFERIDOS) == []


def test_cadastro_fora_do_ar_nao_recusa():
    """A conferência é proteção a mais: sem cadastro, a consulta segue."""
    class Quebrado(FakeQueryExecutor):
        def valores_cadastrados(self, chave, sql):
            raise RuntimeError("banco fora")

    assert conferir(BASE + "pdvs.cidade ILIKE '%CUIBA%'", CONFERIDOS, Quebrado()) == ""


def test_catalogo_traz_as_colunas_conferidas():
    chaves = {c.chave for c in load_catalog().name_checks}
    assert {"cddd.pdvs.cidade", "cddd.utc.cidade", "cddd.forca_vendas.desc_territorio"} <= chaves


@pytest.mark.django_db
def test_orquestrador_recusa_a_cidade_errada_e_corrige(django_user_model):
    """De ponta a ponta: o plano com '%CUIBA%' nem chega ao banco; a
    correção recebe CUIABA (MT) no motivo e a consulta certa roda."""
    conversa = Conversation.objects.create(user=django_user_model.objects.create_user("fernando", password="x"))
    mensagem = Message.objects.create(
        conversation=conversa, direction=Message.Direction.INBOUND, client_message_id="c-1",
        content="qual a venda sell-out de cuibá nos ultimos 3 meses?", status=Message.Status.RECEIVED,
    )
    provider = ScriptedAIProvider(
        [plano(sql=BASE + "pdvs.cidade ILIKE '%CUIBA%'"),
         plano(sql=BASE + "pdvs.cidade = 'CUIABA' AND pdvs.uf = 'MT'")],
        [resposta("Foram 65 unidades.")],
    )
    executor = FakeQueryExecutor([make_result(("und",), [(65.0,)])], cadastro=CADASTRO)

    reply = handle_message(mensagem, channel=FakeChannel(), provider=provider, executor=executor,
                           catalog=load_catalog())

    assert reply.decision == AIReply.Decision.ANSWERED
    tentativas = list(reply.query_runs.order_by("attempt"))
    assert [t.guard_result for t in tentativas] == [QueryRun.GuardResult.REJECTED, QueryRun.GuardResult.APPROVED]
    assert "CUIABA (MT)" in provider.plan_requests[1].error_note
    assert len(executor.executed) == 1 and "'CUIABA'" in executor.executed[0]
