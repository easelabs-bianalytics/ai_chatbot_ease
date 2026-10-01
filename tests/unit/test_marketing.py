"""Bases do Marketing: CRM LINK, transformação, clientes e roteamento (ADR-0032).

Sem rede e sem banco: os clientes usam uma sessão de mentira, e a carga é
testada pelas linhas que produz. A gravação de verdade está em
tests/integration/test_marketing_no_banco.py.
"""

from datetime import datetime, timezone

import pytest

from ai_orchestrator.context import escolher_secoes
from marketing.carga import linhas_da_area_medica, linhas_do_email_mkt
from marketing.crm import crm_link, numero_do_crm, uf_no_crm, uf_valida
from marketing.fontes import AreaMedica, EmailMkt, FonteIndisponivel

AGORA = datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- CRM LINK


@pytest.mark.parametrize("numero, uf, esperado", [
    ("39273", "MG", "MG0039273"),        # só o número, como no Email MKT
    ("0039273", "mg", "MG0039273"),      # zeros a mais e UF minúscula
    ("39.273-0", "SP", "SP0392730"),     # pontuação some, o dígito fica
    ("SP123456", "", "SP0123456"),       # UF colada no CRM
    ("123456/RJ", None, "RJ0123456"),    # UF depois da barra
    ("CRM-PR 25111", "", "PR0025111"),   # com a sigla do conselho
    ("52752479", "RJ", "RJ52752479"),    # mais de 7 dígitos: não corta
    ("39273", "ER", ""),                 # UF inválida, e nenhuma no CRM: sem link
    ("PENDENTE", "SP", ""),              # sem número
    ("000000", "SP", ""),                # só zeros
    ("39273", "", ""),                   # número solto não identifica médico
])
def test_crm_link(numero, uf, esperado):
    """O BI guarda o médico como UF + 7 dígitos (`MG0039273`, 133.337 de
    133.337 em audit.medico). Toda base nova vira esse formato."""
    assert crm_link(numero, uf) == esperado


def test_uf_do_campo_vale_antes_da_escrita_no_crm():
    assert crm_link("SP123456", "MG") == "MG0123456"


def test_pecas_do_crm():
    assert numero_do_crm("0081305") == "81305"
    assert uf_valida(" sp ") == "SP" and uf_valida("ER") == "" and uf_valida("São Paulo") == ""
    assert uf_no_crm("CRM/SP 1234") == "SP"
    assert uf_no_crm("SP ou RJ 1234") == ""  # duas UFs: não escolhe


# ---------------------------------------------------------------- Área Médica


def test_linhas_da_area_medica():
    usuarios = [
        {"nome": "Dra. Ana", "email": "Ana@Example.com", "crm_cro": "12345", "uf": "SP", "cidade": "São Paulo",
         "especialidade": "Neurologia", "tipo_visita_tecnica": "Sim, visita presencial",
         "data_cadastro": "2026-09-25T14:30:00+00:00", "quantidade_acessos": 3, "telefone": "11999990000"},
        {"nome": "Repetido", "email": "ana@example.com", "crm_cro": "1", "uf": "SP"},  # e-mail repetido: sai
        {"nome": "Sem CRM", "email": "b@x.com", "crm_cro": "PENDENTE", "uf": "ER"},
    ]

    linhas = linhas_da_area_medica(usuarios, AGORA)

    assert len(linhas) == 2
    ana = dict(zip(("email", "nome", "telefone", "crm_cro", "uf"), linhas[0][:5]))
    assert ana == {"email": "ana@example.com", "nome": "Dra. Ana", "telefone": "11999990000", "crm_cro": "12345", "uf": "SP"}
    assert linhas[0][8] == datetime(2026, 9, 25, 14, 30, tzinfo=timezone.utc)
    assert linhas[0][11] == "SP0012345"
    assert linhas[1][11] is None


# ---------------------------------------------------------------- Email MKT

CAMPOS = [
    {"id": "12", "title": "CRM"}, {"id": "34", "title": "UF do Conselho"}, {"id": "16", "title": "Senha"},
    {"id": "27", "title": "Especialidade"}, {"id": "74", "title": "Já Prescreve Ease Labs?"},
    {"id": "43", "title": "Última visita"},
]
TAGS = [{"id": "63", "tag": "é-médico"}, {"id": "55", "tag": "Inativo"}]


def _contatos():
    return {
        "contacts": [
            {"id": "8993", "email": "Medico@X.com", "firstName": "João", "lastName": "Silva", "phone": "",
             "cdate": "2024-05-20T06:23:14-05:00", "udate": "2026-01-09T16:37:20-06:00",
             "last_open_date": "2026-09-01 10:00:00", "last_click_date": "0000-00-00 00:00:00",
             "bounced_hard": "0", "bounced_soft": "1"},
            {"id": "9001", "email": "paciente@x.com", "firstName": "Paciente", "cdate": "2026-02-01T00:00:00-03:00"},
        ],
        "fieldValues": [
            {"contact": "8993", "field": "12", "value": "1029053"},
            {"contact": "8993", "field": "34", "value": "RJ"},
            {"contact": "8993", "field": "16", "value": "segredo123"},
            {"contact": "8993", "field": "27", "value": "Clínica médica"},
            {"contact": "8993", "field": "43", "value": "2026-08-10 16:03:00"},
        ],
        "contactTags": [{"contact": "8993", "tag": "63"}, {"contact": "9001", "tag": "55"}],
        "contactLists": [],
    }


def test_linhas_do_email_mkt():
    linhas = linhas_do_email_mkt(_contatos(), CAMPOS, TAGS, AGORA)

    medico, paciente = linhas
    assert medico[0] == 8993 and medico[1] == "medico@x.com" and medico[2] == "João Silva"
    assert (medico[10], medico[11], medico[12]) == ("1029053", "RJ", "RJ1029053")
    assert medico[14] == "Clínica médica"
    assert medico[6] is not None and medico[7] is None   # "0000-00-00" é "nunca"
    assert medico[25] is True and medico[26] is False     # é-médico, não inativo
    assert paciente[12] is None and paciente[26] is True


def test_senha_nunca_e_copiada():
    """O ActiveCampaign tem um campo "Senha" preenchido em contatos antigos.
    Ele não vai para o banco de jeito nenhum."""
    linhas = linhas_do_email_mkt(_contatos(), CAMPOS, TAGS, AGORA)

    assert "segredo123" not in str(linhas)


# ---------------------------------------------------------------- clientes


class _Resposta:
    def __init__(self, corpo, status=200):
        self.status_code, self._corpo = status, corpo

    def json(self):
        return self._corpo


class _Sessao:
    def __init__(self, respostas):
        self.respostas, self.chamadas, self.headers = list(respostas), [], {}

    def get(self, url, params=None, timeout=None):
        self.chamadas.append((url, dict(params or {})))
        return self.respostas.pop(0)


def test_area_medica_pagina_ate_a_ultima(monkeypatch):
    monkeypatch.setattr("marketing.fontes.time.sleep", lambda s: None)
    sessao = _Sessao([
        _Resposta({"data": [{"email": "a"}], "last_page": 2, "total": 2}),
        _Resposta({"data": [{"email": "b"}], "last_page": 2, "total": 2}),
    ])

    usuarios = AreaMedica("https://am", "t", sessao).usuarios()

    assert [u["email"] for u in usuarios] == ["a", "b"]
    assert sessao.chamadas[1][1] == {"page": 2, "per_page": 200}
    assert sessao.headers["Authorization"] == "Bearer t"


def test_area_medica_que_perde_cadastro_no_meio_falha(monkeypatch):
    """Cadastro novo no meio da paginação empurra todo mundo uma posição: um
    cadastro sumiria. Melhor falhar e ficar com o de ontem."""
    monkeypatch.setattr("marketing.fontes.time.sleep", lambda s: None)
    sessao = _Sessao([_Resposta({"data": [{"email": "a"}], "last_page": 1, "total": 2})])

    with pytest.raises(FonteIndisponivel):
        AreaMedica("https://am", "t", sessao).usuarios()


def test_email_mkt_espera_e_tenta_de_novo_no_429(monkeypatch):
    esperas = []
    monkeypatch.setattr("marketing.fontes.time.sleep", esperas.append)
    sessao = _Sessao([
        _Resposta({}, status=429),
        _Resposta({"lists": [{"id": "3"}], "meta": {"total": "1"}}),
    ])

    listas = EmailMkt("https://ac", "t", sessao).listas()

    assert listas == [{"id": "3"}] and 2.0 in esperas
    assert sessao.headers["Api-Token"] == "t"


def test_token_errado_falha_sem_tentar_de_novo(monkeypatch):
    monkeypatch.setattr("marketing.fontes.time.sleep", lambda s: None)
    sessao = _Sessao([_Resposta({}, status=401)])

    with pytest.raises(FonteIndisponivel, match="token"):
        EmailMkt("https://ac", "t", sessao).listas()


def test_email_mkt_contatos_juntam_as_paginas(monkeypatch):
    monkeypatch.setattr("marketing.fontes.time.sleep", lambda s: None)
    sessao = _Sessao([
        _Resposta({"contacts": [{"id": "1"}], "fieldValues": [{"contact": "1"}], "meta": {"total": "2"}}),
        _Resposta({"contacts": [{"id": "2"}], "contactTags": [{"contact": "2"}], "meta": {"total": "2"}}),
    ])
    cliente = EmailMkt("https://ac", "t", sessao)
    cliente.POR_PAGINA = 1

    dados = cliente.contatos()

    assert [c["id"] for c in dados["contacts"]] == ["1", "2"]
    assert len(dados["fieldValues"]) == 1 and len(dados["contactTags"]) == 1
    assert sessao.chamadas[0][1]["include"] == "fieldValues,contactTags,contactLists"


# ---------------------------------------------------------------- roteamento


@pytest.mark.parametrize("pergunta, temas", [
    ("Jarvis, puxe quais os médicos da Área Médica que tiveram cadastro em 2026 e ativos com ultimo login "
     "dentro do último trimestre móvel, verifique se são melhores prescritores Ease Labs", {"marketing", "prescricao"}),
    ("Pegue os médicos do painel da Força de Vendas, e puxe para mim quais estão presentes na Área Médica, e "
     "elenque os representantes por mais médicos cadastrados na base", {"marketing", "forca_vendas"}),
    ("Puxe os médicos da base do email marketing completa e a data de cadastro deles", {"marketing"}),
    ("Como foram as campanhas de e-mail de setembro?", {"marketing"}),
])
def test_perguntas_do_marketing_levam_o_tema(pergunta, temas):
    """As três perguntas de exemplo do Rubens (2026-10-01): o tema do
    Marketing tem de ir junto, senão o modelo não conhece o schema."""
    assert temas <= set(escolher_secoes(pergunta))


def test_campanha_sozinha_continua_do_pbm():
    assert escolher_secoes("Quantos vouchers da campanha de agosto foram usados?")[0] == "pbm"
