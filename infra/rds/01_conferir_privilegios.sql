-- Antes de criar nada: o usuário atual consegue criar role e conceder SELECT?
-- Somente leitura, não altera nada. Rode com o túnel SSM aberto:
--   psql "host=127.0.0.1 port=15432 dbname=<banco> user=<usuario> sslmode=require"

SELECT current_user AS usuario,
       rolsuper     AS superusuario,
       rolcreaterole AS pode_criar_role
FROM pg_roles WHERE rolname = current_user;

-- Quem é dono dos schemas que o chatbot precisa ler. Só o dono (ou um
-- superusuário) consegue conceder SELECT nas tabelas deles.
SELECT nspname AS schema, pg_get_userbyid(nspowner) AS dono
FROM pg_namespace
WHERE nspname IN ('audit', 'cddd', 'estoque_redes', 'pbm', 'ruptura_extrato', 'tdd')
ORDER BY 1;

-- Donos das tabelas: se houver mais de um, o ALTER DEFAULT PRIVILEGES precisa
-- ser repetido para cada um, senão tabela nova nasce invisível para o chatbot.
SELECT schemaname AS schema, tableowner AS dono, count(*) AS tabelas
FROM pg_tables
WHERE schemaname IN ('audit', 'cddd', 'estoque_redes', 'pbm', 'ruptura_extrato', 'tdd')
GROUP BY 1, 2
ORDER BY 1, 2;
