-- Schema SINTÉTICO que imita o banco de negócio (RDS PostgreSQL 16).
--
-- Nenhum dado real: nomes, CNPJs e números são inventados. Serve para os
-- testes do executor e, na Fase 7, para comparar o resultado da consulta que
-- a IA escreve com o da consulta de referência correspondente.
--
-- As colunas seguem o que as consultas de referência usam, incluindo as
-- maiúsculas com aspas do PBM e do TDD, porque é justamente aí que uma
-- consulta gerada costuma errar.

CREATE SCHEMA audit;
CREATE SCHEMA cddd;
CREATE SCHEMA estoque_redes;
CREATE SCHEMA pbm;
CREATE SCHEMA ruptura_extrato;
CREATE SCHEMA tdd;

-- ------------------------------------------------ prescrição médica
CREATE TABLE audit.medico (
    cdgmedico    integer PRIMARY KEY,
    crm          text,
    nome         text,
    espec1       text,
    cidade       text,
    utc_codigo   bigint,
    cep          text
);

CREATE TABLE audit.prescricao (
    cdgmedico        integer,
    cdglaboratorio   text,
    cdgmarca         integer,
    cdgconcentracao  integer,
    cdgapresentacao  integer,
    cdgforma         integer,
    px1              numeric,
    data             date
);

CREATE TABLE audit.molecula_produto_relacao (
    cdgmarca             integer,
    codigoconcentracao   integer,
    codigoapresentacao   integer,
    codigoforma          text,
    cdglaboratorio       text,
    descmole             text
);

CREATE TABLE audit.rx_cadastro_mais_recente (
    crm_link       text,
    nome           text,
    setor          text,
    setor_cliente  text,
    categoria      text,
    classificacao  text,
    potencial      text,
    email          text,
    celular        text
);

CREATE TABLE audit.rx_visitas (
    id_visita        serial PRIMARY KEY,
    crm_norm         text,
    setor            text,
    data_da_visita   timestamp,
    visita_efetiva   text,
    tipo_visita      text,
    comentarios      text
);

-- ------------------------------------------------ sell-out e cadastro
CREATE TABLE cddd.vendas_consolidado (
    cod_anomes         date,
    cod_pdv            text,
    cod_apresentacao   text,
    desc_apresentacao  text,
    und                numeric,
    valor              numeric,
    cod_utc            bigint,
    cod_territorio     integer,
    cod_ct             integer,
    cod_gr             integer
);

CREATE TABLE cddd.vw_sellout_mensal (
    ano_mes            date,
    cod_apresentacao   text,
    desc_apresentacao  text,
    qtd                numeric,
    "QTD_LM"           numeric,
    "Cresc_%"          numeric
);

CREATE TABLE cddd.pdvs (
    cod_pdv        bigint PRIMARY KEY,
    cnpj_pdv       text,
    desc_pdv       text,
    desc_endereco  text,
    bairro         text,
    cidade         text,
    uf             text,
    cep            text,
    cod_utc        bigint,
    cod_subcanal   integer
);

-- Existe no banco real e não deve ser usada para sell-out (está na lista de
-- tabelas bloqueadas do catálogo). Fica aqui para o teste poder provar que o
-- validador recusa mesmo quando a tabela existe.
CREATE TABLE cddd.fato_cdd (
    cod_anomes  date,
    und         numeric
);

CREATE TABLE cddd.forca_vendas (
    cod_utc          bigint,
    cod_territorio   text,
    desc_territorio  text
);

CREATE TABLE cddd.scd_ct_territorio (
    cod_territorio           integer,
    cod_ct                   integer,
    data_saida_territorio    date
);

CREATE TABLE cddd.dim_ct (
    cod_ct              integer,
    nome_abreviado_ct   text,
    email_ct            text
);

CREATE TABLE cddd.dim_gr (
    cod_gr    integer,
    nome_gr   text
);

CREATE TABLE cddd.canal (
    cod_subcanal        integer,
    desc_subcanal       text,
    desc_canal          text,
    desc_grupo_canal    text
);

-- ------------------------------------------------ estoque nas redes
CREATE TABLE estoque_redes.vw_estoque_cd_recente (
    rede               text,
    cnpj               bigint,
    desc_loja          text,
    tipo               text,
    cod_ean            text,
    estoque_qtde       numeric,
    data_recebimento   date
);

CREATE TABLE estoque_redes.vw_forecast_projecao_cd_extrato (
    rede                  text,
    cd                    text,
    estoque               numeric,
    dde_base              numeric,
    compra_arredondada    numeric,
    em_ruptura            boolean,
    dia                   integer
);

CREATE TABLE ruptura_extrato.vw_app_pdvs (
    loja         text,
    rede         text,
    endereco     text,
    cidade       text,
    uf           text,
    telefone     text,
    estoque_un   numeric,
    latitude     double precision,
    longitude    double precision
);

CREATE TABLE ruptura_extrato.dim_cep_geo (
    cep       text,
    lat_ok    double precision,
    lon_ok    double precision
);

CREATE TABLE ruptura_extrato.vw_representantes_ativos (
    cod_territorio      text,
    desc_territorio     text,
    nome_abreviado_ct   text,
    email_ct            text
);

CREATE FUNCTION ruptura_extrato.f_haversine_km(
    lat1 double precision, lon1 double precision,
    lat2 double precision, lon2 double precision
) RETURNS double precision AS $$
    SELECT 6371 * 2 * asin(sqrt(
        power(sin(radians(lat2 - lat1) / 2), 2) +
        cos(radians(lat1)) * cos(radians(lat2)) *
        power(sin(radians(lon2 - lon1) / 2), 2)
    ));
$$ LANGUAGE sql IMMUTABLE;

-- ------------------------------------------------ PBM
-- As colunas do consumidor existem aqui de propósito: é o que permite testar
-- que o validador as recusa (ADR-0008), inclusive num SELECT *.
CREATE TABLE pbm.fato_pbm_transacoes (
    "STATUS_TRN"         text,
    "DATA_REF"           date,
    "EAN"                text,
    "MARCA"              text,
    "QTDE"               text,
    "QTDE_DEVOLVIDA"     text,
    "CNPJ_PDV"           text,
    "NOME_FANTASIA"      text,
    "CIDADE_PDV"         text,
    "UF_PDV"             text,
    "UF_PROFISSIONAL"    text,
    "COD_PROFISSIONAL"   text,
    "NOME_PROFISSIONAL"  text,
    "CPF_CONS"           text,
    "NOME_CONS"          text,
    "E_MAIL"             text,
    "CELULAR"            text
);

-- ------------------------------------------------ mercado (TDD)
CREATE TABLE tdd.dim_pdv (
    "COD_PDV"      integer,
    "CNPJ_PDV"     bigint,
    "DESC_PDV"     text,
    "CIDADE_PDV"   text,
    "UF_PDV"       text,
    "UTC_PDV"      bigint
);

CREATE TABLE tdd.fato_tdd (
    "COD_PDV"            integer,
    "COD_GRUPO"          integer,
    "COD_PERIODO"        text,
    "CAT_UN_MERCADO"     integer,
    "UN_MERCADO"         numeric,
    "R$_PDV_MERCADO"     numeric
);

-- O usuário de leitura enxerga tudo o que existe agora e o que vier depois.
GRANT USAGE ON SCHEMA audit, cddd, estoque_redes, pbm, ruptura_extrato, tdd TO bi_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA audit, cddd, estoque_redes, pbm, ruptura_extrato, tdd TO bi_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA audit, cddd, estoque_redes, pbm, ruptura_extrato, tdd
    GRANT SELECT ON TABLES TO bi_readonly;
GRANT EXECUTE ON FUNCTION ruptura_extrato.f_haversine_km(
    double precision, double precision, double precision, double precision
) TO bi_readonly;
