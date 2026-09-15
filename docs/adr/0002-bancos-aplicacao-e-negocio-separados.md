# ADR-0002: Banco da aplicação separado do banco de negócio

## Status
Aceito — 2026-09-14

## Contexto
Há dois tipos de dado com donos e riscos diferentes:

- conversas, mensagens e auditoria, produzidos pelo próprio chatbot;
- dados de negócio da Ease Labs (prescrição, sell-out, estoque, PBM, força
  de vendas), no Amazon RDS for PostgreSQL 16.13 na AWS, mantidos pelo time
  de BI e usados por outros sistemas.

Misturar os dois exporia o banco de negócio a migrations, escrita
acidental e acoplamento de schema.

## Decisão
- **Banco da aplicação:** PostgreSQL próprio (local via Docker, Railway em
  produção), fonte de verdade das conversas e da auditoria, gerido por
  migrations do Django. Configurado por `APP_DATABASE_URL` (ou `APP_DB_*`).
- **Banco de negócio:** RDS, acessado exclusivamente pelo
  `PostgresReadOnlyExecutor` (`datasource/executors/`) com conexão psycopg2
  explícita, configurada por `ANALYTICS_DATABASE_URL`.

O RDS **não** entra em `DATABASES` do Django: sem alias, sem router, sem
ORM. Assim não existe caminho para `migrate`, `save()` ou query arbitrária
chegar a ele — o único ponto de entrada é o executor, que aplica as
proteções do ADR-0008.

## Consequências
- Testes nunca dependem do RDS: usam `FakeQueryExecutor` ou o
  `analytics_db` sintético local do `docker-compose.yml`.
- Os resultados de consulta ficam registrados no banco da aplicação
  (`QueryRun`), com amostra limitada, para auditoria.
- **Prefixo `APP_` nas variáveis do banco da aplicação** (Fase 1): o
  `bi/.env` já existia com credenciais da AWS, e nomes genéricos
  (`DATABASE_URL`, `POSTGRES_HOST`) poderiam apontar para o RDS e fazer o
  `migrate` rodar lá. No Railway, mapear
  `APP_DATABASE_URL=${{Postgres.DATABASE_URL}}`.
- **Trava na subida:** `config/env.py` recusa iniciar se o banco da
  aplicação apontar para `*.rds.amazonaws.com`. Se um dia a aplicação for
  hospedada com Postgres próprio no RDS, isso exige um novo ADR.
- A suíte de testes usa `config.settings_test`, que não carrega o `.env` e
  aponta sempre para o Postgres local.
