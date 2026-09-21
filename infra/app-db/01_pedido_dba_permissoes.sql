-- ============================================================================
-- PEDIDO À DBA — o que falta para o `rubens_dba` preparar o banco do Jarvis
--
-- O Jarvis (copiloto de dados do BI & Analytics) precisa guardar o que é dele:
-- usuários, histórico de conversas e auditoria. Isso vive num **schema
-- `jarvis` dentro do database `easelabs`**, ao lado de `cockpit`, `trade_fv`,
-- `eventos` e os schemas do warehouse — o mesmo padrão que todo app do
-- cockpit já segue. Não há database novo e não há instância nova.
--
-- Estado em 2026-09-18:
--   ✅ CREATE no database `easelabs` — concedido, o schema pode ser criado.
--   🔲 CREATEROLE — falta, e é só isto que este script pede.
--
-- Roda uma vez, com a conta mestra da instância (ou um membro de
-- `rds_superuser`), em qualquer database:
--
--   psql "host=cockpit-prod-db.cpuoqq0y8xnn.sa-east-1.rds.amazonaws.com \
--         port=5432 dbname=easelabs user=<conta_mestra> sslmode=require" \
--        -f 01_pedido_dba_permissoes.sql
--
-- Se a DBA preferir criar as duas roles ela mesma, este script não é
-- necessário: basta rodar a seção 1 do `02_criar_schema_jarvis.sql` e passar
-- as senhas. O resto do script o `rubens_dba` já consegue executar.
-- ============================================================================

ALTER ROLE rubens_dba CREATEROLE;

-- O que o atributo libera, e só isso:
--
--   CREATEROLE  criar e administrar as roles que ele mesmo criar. No
--               PostgreSQL 16 quem cria uma role vira dono dela e não herda
--               poder sobre as demais: o `rubens_dba` não passa a mexer no
--               `bi_chatbot_ro`, nas roles da DBA nem na conta mestra.
--
-- O que este pedido NÃO inclui, de propósito:
--
--   • CREATEDB — não é mais necessário. A versão anterior deste pedido queria
--     criar um database `jarvis` separado; a decisão mudou para schema no
--     `easelabs` (ver docs/plan.md, Fase 9, seção "Banco da aplicação");
--   • nenhum privilégio novo sobre os dados de negócio (`cddd`, `audit`, `td`,
--     `tdd`, `pbm`, `estoque_redes`) — a leitura do chatbot continua sendo a
--     que o `bi_chatbot_ro` já tem;
--   • nada no schema `trade_fv` nem em qualquer schema existente;
--   • nenhum SUPERUSER e nenhum `rds_superuser`.

-- Conferência: deve devolver rolcreaterole = t
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole
FROM pg_roles
WHERE rolname = 'rubens_dba';

-- E a permissão que já saiu, para o registro: deve devolver t
SELECT has_database_privilege('rubens_dba', 'easelabs', 'CREATE') AS pode_criar_schema;
