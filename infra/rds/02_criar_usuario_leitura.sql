-- Permissões do usuário somente leitura do chatbot de BI (D-01, ADR-0008).
--
-- A role bi_chatbot_ro já existe (criada em 2026-09-16). Este script completa
-- o que faltou: em 2026-09-16 ela conectava, mas não tinha USAGE em nenhum
-- schema, não lia nenhuma tabela e não estava em modo somente leitura.
--
-- Pode rodar direto no DBeaver (sem variáveis de psql), com o master do RDS
-- ou outro usuário que possa conceder nos objetos abaixo e executar
-- ALTER DEFAULT PRIVILEGES pelos donos. Pode rodar de novo sem problema.

-- 1. Mesmo que a aplicação erre, a sessão desta role não escreve, não segura
--    transação aberta e não roda consulta eterna.
ALTER ROLE bi_chatbot_ro SET default_transaction_read_only = on;
ALTER ROLE bi_chatbot_ro SET statement_timeout = '15s';
ALTER ROLE bi_chatbot_ro SET lock_timeout = '10s';
ALTER ROLE bi_chatbot_ro SET idle_in_transaction_session_timeout = '30s';

-- 2. Conexão e leitura nos seis schemas usados pelas consultas de referência.
GRANT CONNECT ON DATABASE easelabs TO bi_chatbot_ro;
GRANT USAGE ON SCHEMA audit, cddd, td, tdd, pbm, estoque_redes TO bi_chatbot_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA audit, cddd, td, tdd, pbm, estoque_redes TO bi_chatbot_ro;

-- 3. Tabelas e views criadas no futuro. Só nascem visíveis se houver default
--    privilege para o dono que as cria. Donos conferidos em 2026-09-16:
--    app_pipelines (audit, cddd, td, pbm, estoque_redes), cockpit_admin
--    (tdd, estoque_redes), dbt_transform (estoque_redes), app_eventos (cddd).
ALTER DEFAULT PRIVILEGES FOR ROLE app_pipelines
    IN SCHEMA audit, cddd, td, pbm, estoque_redes GRANT SELECT ON TABLES TO bi_chatbot_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE cockpit_admin
    IN SCHEMA tdd, estoque_redes GRANT SELECT ON TABLES TO bi_chatbot_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE dbt_transform
    IN SCHEMA estoque_redes GRANT SELECT ON TABLES TO bi_chatbot_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE app_eventos
    IN SCHEMA cddd GRANT SELECT ON TABLES TO bi_chatbot_ro;

-- 4. Conferência (deve voltar 6 linhas, todas com usage = true e tabelas > 0).
SELECT n.nspname AS schema,
       has_schema_privilege('bi_chatbot_ro', n.nspname, 'USAGE') AS usage,
       count(c.oid) FILTER (WHERE has_table_privilege('bi_chatbot_ro', c.oid, 'SELECT')) AS tabelas_legiveis
FROM pg_namespace n
LEFT JOIN pg_class c ON c.relnamespace = n.oid AND c.relkind IN ('r','p','v','m','f')
WHERE n.nspname IN ('audit', 'cddd', 'td', 'tdd', 'pbm', 'estoque_redes')
GROUP BY 1, 2
ORDER BY 1;

-- Quando o schema remuneracao_fv (metas) for criado, ele também vai precisar
-- de USAGE, SELECT e default privilege para o dono.
