#!/bin/sh
# Schema `marketing` no banco analítico SINTÉTICO local (ADR-0032).
#
# O mesmo desenho do infra/rds/05_criar_schema_marketing.sql: uma role que
# escreve só nele (jarvis_mkt_sync) e o usuário de leitura do Jarvis lendo.
# Roda uma vez, quando o volume é criado; num volume que já existe, rode à
# mão:  docker compose exec -T analytics_db sh /docker-entrypoint-initdb.d/04_schema_marketing.sh
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_mkt_sync') THEN
    CREATE ROLE jarvis_mkt_sync LOGIN PASSWORD '${MARKETING_SYNC_PASSWORD:-jarvis_mkt_sync_dev}' NOINHERIT;
  END IF;
END \$\$;
CREATE SCHEMA IF NOT EXISTS marketing AUTHORIZATION jarvis_mkt_sync;
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO jarvis_mkt_sync;
ALTER ROLE jarvis_mkt_sync SET search_path = marketing;
GRANT USAGE ON SCHEMA marketing TO bi_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA marketing TO bi_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE jarvis_mkt_sync IN SCHEMA marketing GRANT SELECT ON TABLES TO bi_readonly;
EOSQL
