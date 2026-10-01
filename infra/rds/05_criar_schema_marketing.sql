-- Schema e role das bases do Marketing: Área Médica e Email MKT (ADR-0032).
--
-- A sincronização diária (task ECS cockpit-prod-jarvis-sync, comando
-- `sincronizar_marketing`) grava aqui o que puxa das duas APIs. O Jarvis lê
-- pelo bi_chatbot_ro, e cruza com audit/cddd em SQL pelo crm_link.
--
-- Mesmo padrão dos schemas `jarvis` e `evolution` (Fase 9): acréscimo num
-- schema novo, sem tocar em dado existente, role sem CREATEDB e com
-- search_path fixo. A regra 6 do sales_force_crm vale: SNAPSHOT ANTES.
--
--   aws rds create-db-snapshot --region sa-east-1 \
--     --db-instance-identifier cockpit-prod-db \
--     --db-snapshot-identifier cockpit-prod-db-antes-jarvis-marketing-AAAAMMDD
--
-- Rodar com o master do RDS (rubens_dba), pelo túnel. A senha NÃO vai aqui:
-- entra como variável do psql, gerada na hora, e vai direto para o secret
-- cockpit-prod-jarvis-mkt-db-password:
--
--   psql "host=127.0.0.1 port=15432 dbname=easelabs user=rubens_dba sslmode=require" \
--        -v ON_ERROR_STOP=1 -v senha_mkt="$SENHA_MKT" \
--        -f infra/rds/05_criar_schema_marketing.sql

-- 1. A role que escreve. Só no schema dela: não enxerga `jarvis` (as
--    perguntas de todo mundo) nem os schemas de negócio.
CREATE ROLE jarvis_mkt_sync LOGIN PASSWORD :'senha_mkt'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

-- PostgreSQL 16: quem cria a role recebe ADMIN sem SET, e o CREATE SCHEMA ...
-- AUTHORIZATION exige poder assumir a role (Fase 9, passo 1). INHERIT FALSE:
-- o rubens_dba não carrega os privilégios dela nas conexões dele.
GRANT jarvis_mkt_sync TO CURRENT_USER WITH SET TRUE, INHERIT FALSE;

CREATE SCHEMA IF NOT EXISTS marketing AUTHORIZATION jarvis_mkt_sync;
GRANT CONNECT ON DATABASE easelabs TO jarvis_mkt_sync;
REVOKE CREATE ON SCHEMA public FROM jarvis_mkt_sync;
ALTER ROLE jarvis_mkt_sync SET search_path = marketing;
-- A carga do Email MKT regrava ~18 mil contatos e ~160 mil vínculos numa
-- transação: 5 minutos de folga sobram.
ALTER ROLE jarvis_mkt_sync SET statement_timeout = '300s';
ALTER ROLE jarvis_mkt_sync SET idle_in_transaction_session_timeout = '120s';

-- 2. Quem lê: o Jarvis (bi_chatbot_ro), nas tabelas de hoje e nas que a
--    sincronização criar depois; e o rubens_dba, para o DBeaver.
GRANT USAGE ON SCHEMA marketing TO bi_chatbot_ro, rubens_dba;
GRANT SELECT ON ALL TABLES IN SCHEMA marketing TO bi_chatbot_ro, rubens_dba;
-- O default privilege é emitido COMO a role dona: com o GRANT ... INHERIT
-- FALSE acima, o `ALTER DEFAULT PRIVILEGES FOR ROLE jarvis_mkt_sync` feito
-- pelo rubens_dba é recusado ("permission denied to change default
-- privileges", 2026-10-01). SET ROLE resolve sem dar herança a ninguém.
SET ROLE jarvis_mkt_sync;
ALTER DEFAULT PRIVILEGES IN SCHEMA marketing GRANT SELECT ON TABLES TO bi_chatbot_ro, rubens_dba;
RESET ROLE;

-- 3. Conferência: dono certo, a role não usa `jarvis` nem `audit`, e o
--    bi_chatbot_ro lê o schema (esperado: marketing | f | f | f | t).
SELECT n.nspname AS schema,
       has_schema_privilege('jarvis_mkt_sync', 'jarvis', 'USAGE') AS mkt_usa_jarvis,
       has_schema_privilege('jarvis_mkt_sync', 'audit', 'USAGE') AS mkt_usa_audit,
       has_schema_privilege('jarvis_mkt_sync', 'public', 'CREATE') AS mkt_cria_em_public,
       has_schema_privilege('bi_chatbot_ro', 'marketing', 'USAGE') AS jarvis_le_marketing
FROM pg_namespace n
WHERE n.nspname = 'marketing';
