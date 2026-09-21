-- ============================================================================
-- Jarvis (copiloto de dados do BI & Analytics) — schema da aplicação
--
-- Quem executa: o `rubens_dba`, pelo túnel SSM aberto ou de dentro da VPC:
--
--   psql "host=127.0.0.1 port=15432 dbname=easelabs user=rubens_dba sslmode=require"
--        -v ON_ERROR_STOP=1 -v senha_app=<senha_forte>
--        -f 02_criar_schema_jarvis.sql
--
-- A senha entra por parâmetro e vai para o Secrets Manager no mesmo comando;
-- não deve ser escrita neste arquivo nem no `.env`.
--
-- O que ele cria, e nada além disso:
--   • uma role (`jarvis_app`, a da aplicação, que escreve);
--   • um SCHEMA (`jarvis`) dentro do database `easelabs`, que já existe.
--
-- O que ele NÃO faz, de propósito:
--   • não cria database nenhum;
--   • não toca em nenhum schema existente (`cockpit`, `cddd`, `trade_fv`, …);
--   • não concede nada sobre os dados de negócio;
--   • não cria tabela — quem cria são as migrações do Django, depois.
--
-- Por que um schema no `easelabs` e não um database separado: é o padrão da
-- casa — todo app do cockpit é um schema aqui com uma role dedicada
-- (`app_trade_fv`, `app_pipelines`, `app_api`, `cockpit`). E o que a ADR-0002
-- protege continua protegido, por privilégio de banco em vez de topologia:
--
--   1. o Django não cria tabela fora do `jarvis`, porque o `search_path` da
--      role é fixo e ela não tem CREATE em nenhum outro schema;
--   2. a suíte de testes não cria `test_*` em produção, porque `jarvis_app`
--      não tem CREATEDB (e `settings_test.py` recusa host de RDS);
--   3. a garantia de somente leitura do chatbot nunca dependeu disto: é a
--      ADR-0008 — outra conexão, outra role (`bi_chatbot_ro`),
--      `default_transaction_read_only` e o `sql_guard`.
--
-- Por que NÃO existe aqui uma role de leitura da auditoria: existiu uma
-- (`jarvis_ro`), criada e descartada em 2026-09-21. Ninguém pediu, e o que ela
-- resolveria já está resolvido — `manage.py bi_report` e o Admin do Django
-- respondem as perguntas de uso, custo e lacunas. Credencial que ninguém usa é
-- só superfície de ataque. Se um dia o time de BI quiser SQL direto nas
-- tabelas de auditoria, são quatro linhas: CREATE ROLE, GRANT USAGE no schema
-- e as duas ALTER DEFAULT PRIVILEGES de SELECT (rodadas com SET ROLE
-- jarvis_app, que é a dona). O que **não** se deve fazer é dar essa leitura ao
-- `bi_chatbot_ro`: é sob essa role que roda o SQL escrito pela IA, e ela
-- passaria a poder consultar as perguntas de todo mundo.
-- ============================================================================

-- 1. Role ---------------------------------------------------------------------
-- Exige CREATEROLE (ver 01_pedido_dba_permissoes.sql). Se já existir, troque
-- CREATE por ALTER ... PASSWORD e siga.
CREATE ROLE jarvis_app LOGIN PASSWORD :'senha_app';

COMMENT ON ROLE jarvis_app IS 'Aplicacao Jarvis: escreve apenas no schema jarvis';

-- No PostgreSQL 16 quem cria uma role recebe ADMIN sobre ela, mas a associacao
-- nasce com SET e INHERIT desligados (conferido em 2026-09-21 na instancia:
-- admin_option = t, set_option = f). E `CREATE SCHEMA ... AUTHORIZATION` exige
-- poder ASSUMIR a role -- sem este GRANT a secao 2 falha com
-- "must be able to SET ROLE".
--
-- INHERIT FALSE e explicito de proposito: sem ele o GRANT adota o rolinherit
-- de quem executa (que costuma ser `t`), e quem roda o script passaria a
-- carregar os privilegios da jarvis_app em TODA conexao. Efeito colateral
-- desagradavel: tabela criada a mao no schema nasceria com o dono errado.
GRANT jarvis_app TO CURRENT_USER WITH SET TRUE, INHERIT FALSE;

-- CONNECT no `easelabs` não é concedido aqui de propósito: PUBLIC já tem, e
-- um GRANT sobre o database exigiria ser dono dele. Se a DBA tiver revogado
-- de PUBLIC, é ela quem concede à role.

-- 2. Schema -------------------------------------------------------------------
-- AUTHORIZATION jarvis_app: a role vira dona e ganha CREATE aqui dentro, sem
-- ganhar CREATE em lugar nenhum. So funciona por causa do GRANT ... WITH SET
-- da secao 1 -- ser membro da role nao basta, e preciso poder assumi-la.
CREATE SCHEMA jarvis AUTHORIZATION jarvis_app;

COMMENT ON SCHEMA jarvis IS 'Jarvis: usuarios, conversas e auditoria (ver docs/plan.md, Fase 9)';

-- É isto que faz as migrações do Django caírem no schema certo, sem depender
-- de ninguém lembrar de setar variável de ambiente. A aplicação repete o
-- mesmo em OPTIONS (-c search_path=jarvis), cinto e suspensório.
ALTER ROLE jarvis_app IN DATABASE easelabs SET search_path = jarvis;

-- 3. Conferência ---------------------------------------------------------------

-- (a) o schema existe e é do jarvis_app. Deve devolver: easelabs | jarvis_app | jarvis
SELECT current_database() AS database,
       nspowner::regrole  AS dono_do_schema,
       nspname            AS schema
FROM pg_namespace WHERE nspname = 'jarvis';

-- (b) a trava que substitui o database separado: `jarvis` é o ÚNICO schema
--     onde o jarvis_app pode criar objeto. Qualquer outra linha com `t` aqui
--     (`public`, tipicamente) é um REVOKE a pedir para a DBA antes do migrate.
SELECT nspname AS schema,
       has_schema_privilege('jarvis_app', nspname, 'CREATE') AS pode_criar
FROM pg_namespace
WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema'
ORDER BY 2 DESC, 1;

-- (c) sem CREATEDB: é o que impede a suíte de testes de criar `test_*` aqui.
--     Deve devolver f, f.
SELECT rolcreatedb, rolsuper FROM pg_roles WHERE rolname = 'jarvis_app';

-- (d) a associacao do passo 1: deve devolver set_option = t e inherit = f.
--     INHERIT ligado aqui faria quem roda o script carregar os privilegios da
--     jarvis_app sem pedir, em toda conexao.
SELECT r.rolname, m.admin_option, m.inherit_option, m.set_option
FROM pg_auth_members m
  JOIN pg_roles r ON r.oid = m.roleid
  JOIN pg_roles u ON u.oid = m.member
WHERE u.rolname = CURRENT_USER AND r.rolname = 'jarvis_app';
