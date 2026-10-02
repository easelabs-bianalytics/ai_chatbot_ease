-- Tabelas do schema `marketing` (ADR-0032).
--
-- Criadas e mantidas pela sincronização (`manage.py sincronizar_marketing`),
-- conectada como a role dona do schema (jarvis_mkt_sync). Idempotente: roda
-- no começo de toda carga. O schema e a role nascem antes, no script de
-- banco (infra/rds/05_criar_schema_marketing.sql), que também dá SELECT ao
-- bi_chatbot_ro — é por ele que o Jarvis lê.
--
-- Toda tabela de médico traz `crm_link` (UF + 7 dígitos, o formato de
-- audit.medico.crm e de audit.rx_cadastro_mais_recente.crm_link), montado na
-- carga. O dado como veio da fonte fica ao lado, para conferência.

CREATE TABLE IF NOT EXISTS marketing.sincronizacoes (
    id             bigserial PRIMARY KEY,
    fonte          text NOT NULL,           -- 'area_medica' | 'email_mkt' | 'medicos_660'
    iniciada_em    timestamptz NOT NULL DEFAULT now(),
    terminada_em   timestamptz,
    status         text NOT NULL,           -- 'rodando' | 'ok' | 'falhou'
    linhas         jsonb NOT NULL DEFAULT '{}'::jsonb,
    erro           text NOT NULL DEFAULT ''
);

-- Área Médica: um registro por cadastro, como a API devolve.
CREATE TABLE IF NOT EXISTS marketing.area_medica_usuarios (
    email                text PRIMARY KEY,
    nome                 text,
    telefone             text,
    crm_cro              text,                -- como veio (CRM, CRO, CRMV ou CRF)
    uf                   text,
    cidade               text,
    especialidade        text,
    tipo_visita_tecnica  text,
    data_cadastro        timestamptz,
    quantidade_acessos   integer,             -- logins desde o início da contagem
    crm_numero           text,                -- só os dígitos
    crm_link             text,                -- UF + 7 dígitos; vazio sem UF ou número
    sincronizado_em      timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS area_medica_usuarios_crm_link ON marketing.area_medica_usuarios (crm_link);
-- CRM, CRO, CRMV ou CRF, pela especialidade: só quem tem CRM ganha crm_link
-- (dentista com CRO PR 33262 não é o médico de CRM PR 33262).
ALTER TABLE marketing.area_medica_usuarios ADD COLUMN IF NOT EXISTS conselho text;
-- Último login, que a API passou a devolver em 2026-10-01 (vazio em todos
-- os cadastros nesse dia: enche a partir dos logins seguintes).
ALTER TABLE marketing.area_medica_usuarios ADD COLUMN IF NOT EXISTS ultimo_acesso timestamptz;

-- Retrato diário da quantidade de acessos. A API não tem a data do último
-- login: "acessou no período" é a contagem ter subido entre dois retratos
-- (só vale a partir do primeiro retrato, 2026-10-01).
CREATE TABLE IF NOT EXISTS marketing.area_medica_acessos_diarios (
    data                date NOT NULL,
    email               text NOT NULL,
    crm_link            text,
    quantidade_acessos  integer,
    PRIMARY KEY (data, email)
);

-- Email MKT (ActiveCampaign): um registro por contato.
CREATE TABLE IF NOT EXISTS marketing.email_contatos (
    contato_id              bigint PRIMARY KEY,
    email                   text,
    nome                    text,
    telefone                text,
    criado_em               timestamptz,      -- cdate: entrada na base
    atualizado_em           timestamptz,
    ultima_abertura         timestamptz,      -- last_open_date
    ultimo_clique           timestamptz,      -- last_click_date
    bounces_hard            integer,
    bounces_soft            integer,
    crm_numero              text,             -- campo "CRM" (só o número)
    uf_conselho             text,             -- campo "UF do Conselho"
    crm_link                text,
    profissao               text,             -- "Qual sua profissão?"
    especialidade           text,
    categoria               text,
    potencial               text,
    representante           text,
    ultima_visita           timestamptz,
    ja_prescreve_cannabis   text,
    ja_prescreve_ease       text,
    participa_mais_alivio   text,
    tipo_visita             text,             -- "Gostaria de receber visita?"
    cidade_estado           text,
    estado_atuacao          text,
    e_medico                boolean NOT NULL DEFAULT false,  -- tag "é-médico"
    inativo                 boolean NOT NULL DEFAULT false,  -- tag "Inativo"
    campos                  jsonb NOT NULL DEFAULT '{}'::jsonb,  -- todos os campos, pelo título
    sincronizado_em         timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS email_contatos_crm_link ON marketing.email_contatos (crm_link);
CREATE INDEX IF NOT EXISTS email_contatos_email ON marketing.email_contatos (lower(email));
ALTER TABLE marketing.email_contatos ADD COLUMN IF NOT EXISTS conselho text;

CREATE TABLE IF NOT EXISTS marketing.email_listas (
    lista_id    bigint PRIMARY KEY,
    nome        text,
    criada_em   timestamptz
);

-- status: 1 = inscrito, 2 = descadastrado, 3 = descadastrado por bounce,
-- 0 = não confirmado (é o código do ActiveCampaign).
CREATE TABLE IF NOT EXISTS marketing.email_listas_do_contato (
    contato_id    bigint NOT NULL,
    lista_id      bigint NOT NULL,
    status        integer,
    inscrito      boolean NOT NULL,
    inscrito_em   timestamptz,
    atualizado_em timestamptz,
    PRIMARY KEY (contato_id, lista_id)
);

CREATE TABLE IF NOT EXISTS marketing.email_tags (
    tag_id     bigint PRIMARY KEY,
    tag        text,
    contatos   integer
);

CREATE TABLE IF NOT EXISTS marketing.email_tags_do_contato (
    contato_id  bigint NOT NULL,
    tag_id      bigint NOT NULL,
    aplicada_em timestamptz,
    PRIMARY KEY (contato_id, tag_id)
);

CREATE TABLE IF NOT EXISTS marketing.email_campanhas (
    campanha_id       bigint PRIMARY KEY,
    nome              text,
    tipo              text,
    status            integer,
    enviada_em        timestamptz,
    enviados          integer,
    aberturas         integer,
    aberturas_unicas  integer,
    cliques           integer,
    cliques_unicos    integer,
    descadastros      integer,
    bounces_hard      integer,
    bounces_soft      integer,
    automacao_id      bigint
);

-- Base 660: retrato fixo, carregado da planilha pelo comando
-- `carregar_medicos_660` (não pela sincronização diária). Um registro por
-- linha da planilha; o médico liga pelo crm_link.
CREATE TABLE IF NOT EXISTS marketing.medicos_660 (
    nome               text,
    crm_numero         text,                -- "Número Registro", como veio
    uf_registro        text,
    especialidade      text,
    especialidade_2    text,
    estado             text,
    cidade             text,
    cep                text,
    bairro             text,
    endereco           text,
    telefone           text,
    telefone_2         text,
    telefone_3         text,
    email              text,
    valor_online       numeric(10, 2),      -- preço da consulta; vazio = indisponível
    valor_presencial   numeric(10, 2),
    crm_link_planilha  text,                -- o CRM LINK da planilha, sem os zeros
    crm_link           text,                -- UF + 7 dígitos
    carregado_em       timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS medicos_660_crm_link ON marketing.medicos_660 (crm_link);
