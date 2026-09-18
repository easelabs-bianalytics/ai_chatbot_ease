"""Casos de validação x documento de referência.

A suíte da Fase 7 só vale se acompanhar o documento: um caso que aponta
para uma consulta que mudou compararia a IA com um gabarito que ninguém
mais reconhece como certo.
"""

import pytest

from catalog.errors import CatalogError
from catalog.loader import load_catalog
from datasource.sql_guard import validate_sql
from reporting.cases import (
    CaseSuite,
    Troca,
    ValidationCase,
    aplicar_trocas,
    conferir_regras,
    ligar_parametros,
    load_cases,
    normalizar_sql,
    sql_gabarito,
)


@pytest.fixture(scope="module")
def catalogo():
    return load_catalog()


@pytest.fixture(scope="module")
def suite():
    return load_cases()


def test_toda_consulta_do_documento_tem_ao_menos_um_caso(catalogo, suite):
    """O documento foi reescrito inteiro para cobrir o modelo de negócio; uma
    consulta sem caso é uma parte dele que ninguém confere se a IA entende."""
    cobertas = {c.referencia for c in suite.casos}
    faltando = sorted({r.id for r in catalogo.references} - cobertas)

    assert faltando == []


def test_casos_apontam_para_referencias_que_existem(catalogo, suite):
    ids = {r.id for r in catalogo.references}
    inexistentes = sorted({c.referencia for c in suite.casos if c.referencia} - ids)

    assert inexistentes == []


def test_regras_de_negocio_apontam_para_referencias_que_existem(catalogo, suite):
    ids = {r.id for r in catalogo.references}
    inexistentes = sorted({i for r in suite.regras for i in r.referencias} - ids)

    assert inexistentes == []


def test_todo_gabarito_e_montado_e_aprovado_pelo_validador(catalogo, suite):
    """Gabarito que o validador recusaria não roda, e a comparação com a IA
    viraria reprovação de mentira."""
    problemas = {}
    for caso in suite.casos:
        # Casos sem comparação de resultado também entram quando têm trocas:
        # é a troca que apodrece quando o documento muda.
        if not (caso.tem_gabarito or caso.trocas):
            continue
        try:
            sql = sql_gabarito(caso, catalogo)
        except CatalogError as exc:
            problemas[caso.id] = str(exc)
            continue
        resultado = validate_sql(sql, catalogo)
        if not resultado.approved:
            problemas[caso.id] = resultado.reason

    assert problemas == {}


def test_gabarito_cumpre_as_proprias_regras_de_negocio(catalogo, suite):
    """Se o gabarito reprova nas regras, a regra está errada — e reprovaria a
    IA justamente quando ela acerta."""
    falhas = {}
    for caso in suite.casos:
        if not (caso.tem_gabarito or caso.trocas):
            continue
        erros = conferir_regras(sql_gabarito(caso, catalogo), caso, suite)
        if erros:
            falhas[caso.id] = erros

    assert falhas == {}


def test_casos_de_referencia_mudam_a_pergunta_do_documento(catalogo, suite):
    """Repetir a pergunta de exemplo testaria cópia, não interpretação."""
    documento = catalogo.references_text.lower()
    copiadas = [c.id for c in suite.casos if f'"{c.pergunta.lower()}"' in documento]

    assert copiadas == []


def test_suite_cobre_os_comportamentos_que_o_documento_pede(suite):
    grupos = {c.grupo for c in suite.casos}
    esperados = {e for c in suite.casos for e in c.esperado}

    assert {"esclarecimento", "fora_de_escopo", "indisponivel", "seguranca", "seguimento"} <= grupos
    assert {"clarify", "out_of_scope", "indisponivel"} <= esperados


def test_troca_que_nao_existe_mais_no_documento_falha_alto():
    """Se o time de BI reescrever a consulta, o caso precisa ser revisto — e
    não comparar em silêncio com a consulta antiga."""
    with pytest.raises(CatalogError, match="documento mudou"):
        aplicar_trocas("SELECT 1", [Troca(de="LIMIT 10", para="LIMIT 5")], "X01")


def test_parametro_sem_valor_falha():
    with pytest.raises(CatalogError, match=":uf"):
        ligar_parametros("SELECT 1 WHERE uf = :uf", {}, "X01")


def test_ligar_parametros_nao_confunde_cast_nem_comentario():
    sql = "SELECT x::text FROM t WHERE c = :cnpj::bigint -- use :outro aqui"

    ligado = ligar_parametros(sql, {"cnpj": "0123"}, "X01")

    assert ligado == "SELECT x::text FROM t WHERE c = '0123'::bigint -- use :outro aqui"


def test_texto_do_parametro_e_escapado():
    assert ligar_parametros("SELECT :n", {"n": "D'Ávila"}, "X01") == "SELECT 'D''Ávila'"


def test_normalizacao_ignora_alias_espaco_e_caixa_mas_preserva_decimal():
    assert normalizar_sql("WHERE dc_1.desc_canal <> 'HOSPITALAR'") == "wheredesc_canal<>'hospitalar'"
    assert "0.89" in normalizar_sql("CASE WHEN total - FLOOR(total) > 0.89")
    assert normalizar_sql("SELECT 1 -- comentário") == "select1"


def _caso(**campos):
    base = dict(id="X01", grupo="referencia", pergunta="p", esperado=("answer_with_data",), referencia="R1")
    return ValidationCase(**{**base, **campos})


def test_regra_aceita_qualquer_alternativa():
    caso = _caso(sql_deve_conter=(("desc_canal<>'hospitalar'", "desc_canal!='hospitalar'"),))
    suite = CaseSuite(hoje="2026-09-16", regras=(), casos=(caso,))

    assert conferir_regras("SELECT 1 FROM t WHERE c.desc_canal != 'HOSPITALAR'", caso, suite) == []


def test_regra_aponta_o_que_faltou_e_o_que_sobrou():
    caso = _caso(
        sql_deve_conter=(("dia=0",),),
        sql_nao_deve_conter=(("vw_sell_out",),),
    )
    suite = CaseSuite(hoje="2026-09-16", regras=(), casos=(caso,))

    falhas = conferir_regras("SELECT pbm FROM cddd.vw_sell_out", caso, suite)

    assert any("faltou dia=0" in f for f in falhas)
    assert any("não devia conter vw_sell_out" in f for f in falhas)


def test_id_de_caso_repetido_e_erro(tmp_path):
    arquivo = tmp_path / "casos.yaml"
    arquivo.write_text(
        "hoje: '2026-09-16'\ncasos:\n"
        "  - {id: X, grupo: seguranca, pergunta: a, esperado: out_of_scope}\n"
        "  - {id: X, grupo: seguranca, pergunta: b, esperado: out_of_scope}\n",
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="repetido"):
        load_cases(arquivo)


def test_esperado_desconhecido_e_erro(tmp_path):
    arquivo = tmp_path / "casos.yaml"
    arquivo.write_text(
        "hoje: '2026-09-16'\ncasos:\n"
        "  - {id: X, grupo: seguranca, pergunta: a, esperado: talvez}\n",
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="esperado inválido"):
        load_cases(arquivo)
