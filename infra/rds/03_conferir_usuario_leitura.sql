-- Prova que a role ficou como deveria. Rode CONECTADO COMO bi_chatbot_ro:
--   psql "host=127.0.0.1 port=15432 dbname=<banco> user=bi_chatbot_ro sslmode=require"

SELECT current_user, current_setting('default_transaction_read_only') AS somente_leitura;

-- Tem de dar erro: "cannot execute CREATE TABLE in a read-only transaction".
CREATE TABLE public.teste_escrita_chatbot (i int);

-- Tem de funcionar (uma linha por tabela que o chatbot enxerga).
SELECT table_schema, count(*) AS tabelas_visiveis
FROM information_schema.tables
WHERE table_schema IN ('audit', 'cddd', 'estoque_redes', 'pbm', 'ruptura_extrato', 'tdd')
GROUP BY 1 ORDER BY 1;
