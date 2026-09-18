-- ============================================================================
-- Jarvis (copiloto de dados do BI & Analytics) — criação do banco da aplicação
--
-- Quem executa: o `rubens_dba`, depois que a DBA rodar o
-- `01_pedido_dba_permissoes.sql` (que lhe dá CREATEDB e CREATEROLE).
-- Roda uma vez, pelo túnel SSM aberto ou de dentro da VPC:
--
--   psql "host=127.0.0.1 port=15432 dbname=postgres user=rubens_dba sslmode=require"
--        -v ON_ERROR_STOP=1 -v senha_app=<senha_forte> -v senha_ro=<senha_forte>
--        -f 02_criar_banco_jarvis.sql
--
-- As senhas entram por parâmetro e vão para o Secrets Manager no deploy; não
-- devem ser escritas neste arquivo nem no `.env`.
--
-- O que ele cria, e nada além disso:
--   • um DATABASE novo (`jarvis`), separado do `easelabs`;
--   • duas roles (`jarvis_app`, que escreve, e `jarvis_ro`, que só lê);
--   • um SCHEMA (`jarvis`) dentro desse database.
--
-- O que ele NÃO faz, de propósito:
--   • não toca em nenhum schema existente (`cddd`, `audit`, `trade_fv`, …);
--   • não concede nada sobre os dados de negócio;
--   • não cria tabela — quem cria são as migrações do Django, depois.
--
-- Por que um DATABASE separado e não um schema dentro do `easelabs`: no
-- PostgreSQL não existe acesso entre databases sem FDW. Assim a role que
-- escreve (`jarvis_app`) não alcança os dados de negócio nem por engano, e a
-- leitura-apenas do chatbot continua sendo uma propriedade da topologia, não
-- um acerto de GRANT que alguém pode desfazer sem perceber.
-- ============================================================================

-- 1. Roles --------------------------------------------------------------------
-- Se já existirem, troque CREATE por ALTER ... PASSWORD e siga.
CREATE ROLE jarvis_app LOGIN PASSWORD :'senha_app';
CREATE ROLE jarvis_ro  LOGIN PASSWORD :'senha_ro';

COMMENT ON ROLE jarvis_app IS 'Aplicacao Jarvis: le e escreve o proprio banco';
COMMENT ON ROLE jarvis_ro  IS 'BI & Analytics: le a auditoria do Jarvis';

-- 2. Database -----------------------------------------------------------------
-- Sem TEMPLATE nem LC_*: herda o padrao da instancia, que e o que a DBA ja
-- validou. Forcar um locale aqui e a forma mais comum de o script falhar.
CREATE DATABASE jarvis OWNER jarvis_app ENCODING 'UTF8';

REVOKE ALL ON DATABASE jarvis FROM PUBLIC;
GRANT CONNECT ON DATABASE jarvis TO jarvis_app, jarvis_ro;

-- 3. Schema, dentro do database novo ------------------------------------------
\connect jarvis

CREATE SCHEMA jarvis AUTHORIZATION jarvis_app;

-- O `public` fica fechado: o app nao usa, e schema aberto e porta de entrada.
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- As migracoes do Django criam as tabelas no schema certo por causa disto.
ALTER ROLE jarvis_app IN DATABASE jarvis SET search_path = jarvis;
ALTER ROLE jarvis_ro  IN DATABASE jarvis SET search_path = jarvis;

-- Leitura para o time de BI, inclusive nas tabelas que ainda nao existem.
GRANT USAGE ON SCHEMA jarvis TO jarvis_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE jarvis_app IN SCHEMA jarvis
  GRANT SELECT ON TABLES TO jarvis_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE jarvis_app IN SCHEMA jarvis
  GRANT USAGE, SELECT ON SEQUENCES TO jarvis_ro;

-- 4. Conferencia ---------------------------------------------------------------
-- Deve devolver: jarvis | jarvis_app | jarvis
SELECT current_database() AS database,
       nspowner::regrole  AS dono_do_schema,
       nspname            AS schema
FROM pg_namespace WHERE nspname = 'jarvis';
