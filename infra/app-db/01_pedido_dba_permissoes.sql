-- ============================================================================
-- PEDIDO À DBA — permissões para o rubens_dba criar o banco do Jarvis
--
-- O Jarvis (copiloto de dados do BI & Analytics) precisa de um banco próprio
-- para o que é dele: usuários, histórico de conversas e auditoria. Ele não
-- guarda nada disso hoje na AWS — roda local.
--
-- Este script dá ao `rubens_dba` o poder de criar ESSE banco e as roles dele.
-- Roda uma vez, com a conta mestra da instância (ou um membro de
-- `rds_superuser`), em qualquer database:
--
--   psql "host=cockpit-prod-db.cpuoqq0y8xnn.sa-east-1.rds.amazonaws.com \
--         port=5432 dbname=postgres user=<conta_mestra> sslmode=require" \
--        -f 01_pedido_dba_permissoes.sql
-- ============================================================================

ALTER ROLE rubens_dba CREATEDB CREATEROLE;

-- O que cada atributo libera, e só isso:
--
--   CREATEDB    criar databases novos. Não dá acesso a nenhum database que já
--               existe, nem ao `easelabs`.
--   CREATEROLE  criar e administrar roles que ele mesmo criar. No PostgreSQL 16
--               quem cria uma role vira dono dela e não herda poder sobre as
--               demais: o `rubens_dba` não passa a mexer em `bi_chatbot_ro`,
--               em roles da DBA nem na conta mestra.
--
-- O que este pedido NÃO inclui, de propósito:
--
--   • nenhum privilégio novo sobre os dados de negócio (`cddd`, `audit`, `td`,
--     `tdd`, `pbm`, `estoque_redes`) — a leitura do chatbot continua sendo a
--     que o `bi_chatbot_ro` já tem;
--   • nada no schema `trade_fv` nem em qualquer schema existente;
--   • nenhum SUPERUSER e nenhum `rds_superuser`.

-- Conferência: deve devolver rolcreatedb = t e rolcreaterole = t
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole
FROM pg_roles
WHERE rolname = 'rubens_dba';
