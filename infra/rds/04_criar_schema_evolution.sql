-- Schema e role da Evolution API, a ponte do Jarvis com o WhatsApp (ADR-0028).
--
-- A Evolution guarda aqui só a SESSÃO do número (as chaves do aparelho
-- conectado) e o cadastro da instância — as mensagens não: o service sobe
-- com DATABASE_SAVE_DATA_* = false. É o que permite a task morrer e voltar
-- sem pedir o QR de novo.
--
-- Mesmo padrão do schema `jarvis` (Fase 9): acréscimo num schema novo, sem
-- tocar em dado existente, role sem CREATEDB e com search_path fixo. Ainda
-- assim, a regra 6 do sales_force_crm vale: SNAPSHOT ANTES.
--
--   aws rds create-db-snapshot --region sa-east-1 \
--     --db-instance-identifier cockpit-prod-db \
--     --db-snapshot-identifier cockpit-prod-db-antes-jarvis-evolution-AAAAMMDD
--
-- Rodar com o master do RDS. A senha NÃO vai aqui: troque o marcador na hora
-- e guarde a URI completa no secret cockpit-prod-jarvis-evolution-db-uri:
--
--   postgresql://jarvis_evolution:<senha>@<host>:5432/easelabs?schema=evolution&sslmode=require

CREATE ROLE jarvis_evolution LOGIN PASSWORD '<troque-pela-senha-gerada>'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

-- O Prisma (dentro da Evolution) cria e migra as próprias tabelas: a role é
-- dona do schema dela, e só dele.
CREATE SCHEMA IF NOT EXISTS evolution AUTHORIZATION jarvis_evolution;
GRANT CONNECT ON DATABASE easelabs TO jarvis_evolution;
REVOKE CREATE ON SCHEMA public FROM jarvis_evolution;
ALTER ROLE jarvis_evolution SET search_path = evolution;
ALTER ROLE jarvis_evolution SET statement_timeout = '30s';
ALTER ROLE jarvis_evolution SET idle_in_transaction_session_timeout = '60s';

-- Conferência: dono do schema certo, e nenhum acesso aos schemas de negócio
-- nem ao do Jarvis (as três últimas colunas devem voltar false).
SELECT n.nspname AS schema_dono,
       has_schema_privilege('jarvis_evolution', 'jarvis', 'USAGE') AS usa_jarvis,
       has_schema_privilege('jarvis_evolution', 'cddd', 'USAGE') AS usa_cddd,
       has_schema_privilege('jarvis_evolution', 'public', 'CREATE') AS cria_em_public
FROM pg_namespace n
WHERE n.nspname = 'evolution';
