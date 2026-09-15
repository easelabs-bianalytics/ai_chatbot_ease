#!/bin/sh
# Usuário somente leitura do banco analítico SINTÉTICO local.
#
# Reproduz a camada 1 do ADR-0008 (permissão do próprio banco), para que os
# testes provem que uma escrita é recusada pelo Postgres e não só pelo nosso
# código. No RDS o equivalente é a dependência D-01.
#
# Roda uma única vez, quando o volume do container é criado.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE bi_readonly LOGIN PASSWORD '${ANALYTICS_READONLY_PASSWORD}';
ALTER ROLE bi_readonly SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO bi_readonly;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
EOSQL
