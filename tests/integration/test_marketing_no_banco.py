"""A sincronização do Marketing num Postgres de verdade (ADR-0032).

Roda no `analytics_db` sintético, com a role que escreve só no schema
`marketing` (jarvis_mkt_sync) e o usuário de leitura do Jarvis conferindo —
o mesmo desenho do RDS (infra/rds/05_criar_schema_marketing.sql). Prova:

1. a carga grava as duas fontes e o Jarvis lê o resultado;
2. carregar de novo substitui, não duplica;
3. fonte que falha não apaga o que já estava, e a outra segue;
4. a role de escrita não enxerga os schemas de negócio.
"""

import os

import psycopg2
import pytest

from marketing.fontes import AreaMedicaFake, EmailMktFake, FonteIndisponivel
from marketing.sincronizar import sincronizar

ESCRITA = os.environ.get(
    "TEST_MARKETING_DATABASE_URL", "postgresql://jarvis_mkt_sync:jarvis_mkt_sync_dev@localhost:5435/analytics"
)
LEITURA = os.environ.get("TEST_ANALYTICS_DATABASE_URL", "postgresql://bi_readonly:bi_readonly_dev@localhost:5435/analytics")

USUARIOS = [
    {"nome": "Dra. Ana", "email": "ana@x.com", "crm_cro": "39273", "uf": "MG", "data_cadastro": "2026-03-01T10:00:00+00:00",
     "quantidade_acessos": 2},
    {"nome": "Dr. Bruno", "email": "bruno@x.com", "crm_cro": "PENDENTE", "uf": "ER", "data_cadastro": "2025-05-01T10:00:00+00:00",
     "quantidade_acessos": 0},
]
EMAIL = EmailMktFake(
    contatos={
        "contacts": [{"id": "1", "email": "ana@x.com", "firstName": "Ana", "cdate": "2024-01-01T00:00:00-03:00"}],
        "fieldValues": [{"contact": "1", "field": "12", "value": "39273"}, {"contact": "1", "field": "34", "value": "MG"}],
        "contactTags": [{"contact": "1", "tag": "63", "cdate": "2024-01-02T00:00:00-03:00"}],
        "contactLists": [{"contact": "1", "list": "16", "status": "1", "sdate": "2024-01-01T00:00:00-03:00"}],
    },
    campos=[{"id": "12", "title": "CRM"}, {"id": "34", "title": "UF do Conselho"}],
    listas=[{"id": "16", "name": "[GERAL] Área Médica", "cdate": "2022-09-13T09:32:40-05:00"}],
    tags=[{"id": "63", "tag": "é-médico", "subscriber_count": "1"}],
    campanhas=[{"id": "7", "name": "Newsletter", "type": "single", "status": "5", "sdate": "2026-09-10T08:00:00-03:00",
                "send_amt": "100", "uniqueopens": "40", "uniquelinkclicks": "5"}],
)


@pytest.fixture
def escrita():
    try:
        conexao = psycopg2.connect(ESCRITA, connect_timeout=5)
    except psycopg2.OperationalError:
        pytest.skip("analytics_db local sem o schema marketing (infra/analytics_db/init/04_schema_marketing.sh)")
    yield conexao
    conexao.close()


def _conectar():
    return psycopg2.connect(ESCRITA, connect_timeout=5)


def _ler(sql):
    with psycopg2.connect(LEITURA) as conexao, conexao.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


def test_carga_grava_as_duas_fontes_e_o_jarvis_le(escrita):
    resultado = sincronizar(_conectar, AreaMedicaFake(USUARIOS), EMAIL)

    assert resultado["area_medica"] == {"status": "ok", "linhas": {"usuarios": 2, "com_crm_link": 1}}
    assert resultado["email_mkt"]["status"] == "ok"
    assert _ler("SELECT email, crm_link FROM marketing.area_medica_usuarios ORDER BY email") == [
        ("ana@x.com", "MG0039273"), ("bruno@x.com", None),
    ]
    # Área Médica × Email MKT pelo CRM LINK, como o Jarvis vai fazer.
    assert _ler(
        "SELECT a.nome, e.contato_id, e.e_medico FROM marketing.area_medica_usuarios a "
        "JOIN marketing.email_contatos e ON e.crm_link = a.crm_link"
    ) == [("Dra. Ana", 1, True)]
    assert _ler("SELECT inscrito FROM marketing.email_listas_do_contato") == [(True,)]
    assert _ler("SELECT count(*) FROM marketing.area_medica_acessos_diarios WHERE email = 'ana@x.com'")[0][0] >= 1
    assert _ler(
        "SELECT status FROM marketing.sincronizacoes WHERE fonte = 'email_mkt' ORDER BY id DESC LIMIT 1"
    ) == [("ok",)]


def test_carregar_de_novo_substitui_sem_duplicar(escrita):
    sincronizar(_conectar, AreaMedicaFake(USUARIOS), EMAIL)
    sincronizar(_conectar, AreaMedicaFake(USUARIOS[:1]), EMAIL)

    assert _ler("SELECT count(*) FROM marketing.area_medica_usuarios") == [(1,)]
    assert _ler("SELECT count(*) FROM marketing.email_contatos") == [(1,)]


def test_fonte_que_falha_nao_apaga_o_que_estava(escrita):
    sincronizar(_conectar, AreaMedicaFake(USUARIOS), EMAIL)

    resultado = sincronizar(_conectar, AreaMedicaFake(USUARIOS[:1]),
                            EmailMktFake(erro=FonteIndisponivel("/api/3/contacts: HTTP 503")))

    assert resultado["email_mkt"]["status"] == "falhou"
    assert resultado["area_medica"]["status"] == "ok"
    assert _ler("SELECT count(*) FROM marketing.email_contatos") == [(1,)]  # o de antes
    assert _ler(
        "SELECT status, erro FROM marketing.sincronizacoes WHERE fonte = 'email_mkt' ORDER BY id DESC LIMIT 1"
    ) == [("falhou", "FonteIndisponivel: /api/3/contacts: HTTP 503")]


def test_role_de_escrita_nao_enxerga_o_negocio(escrita):
    with escrita.cursor() as cursor, pytest.raises(psycopg2.errors.InsufficientPrivilege):
        cursor.execute("SELECT 1 FROM audit.medico LIMIT 1")
    escrita.rollback()


def test_base_660_grava_substitui_e_o_jarvis_le(escrita):
    """A Base 660 vai para o mesmo schema, pela mesma role: carregar de novo
    substitui, e o usuário de leitura do Jarvis enxerga a tabela."""
    from datetime import datetime, timezone

    from marketing.base_660 import COLUNAS, gravar_base_660
    from marketing.sincronizar import preparar

    preparar(escrita)
    agora = datetime(2026, 10, 2, tzinfo=timezone.utc)
    linha = {c: None for c in COLUNAS} | {"nome": "Dr. Mário", "crm_link": "PI0004896", "carregado_em": agora}
    for _ in range(2):
        resumo = gravar_base_660(escrita, [tuple(linha[c] for c in COLUNAS)])
        escrita.commit()

    assert resumo == {"medicos": 1, "com_crm_link": 1, "crm_links": 1}
    with psycopg2.connect(LEITURA, connect_timeout=5) as leitura, leitura.cursor() as cursor:
        cursor.execute("SELECT crm_link FROM marketing.medicos_660")
        assert cursor.fetchall() == [("PI0004896",)]
