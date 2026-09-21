# ADR-0002: Banco da aplicação separado do banco de negócio

## Status
Aceito — 2026-09-14 · **Revisto em 2026-09-21** (deploy na AWS, Fase 9):
a separação deixou de ser por servidor e passou a ser por schema e
privilégio de banco.

## Contexto
Há dois tipos de dado com donos e riscos diferentes:

- conversas, mensagens e auditoria, produzidos pelo próprio chatbot;
- dados de negócio da Ease Labs (prescrição, sell-out, estoque, PBM, força
  de vendas), no Amazon RDS for PostgreSQL 16.13 na AWS, mantidos pelo time
  de BI e usados por outros sistemas.

Misturar os dois exporia o banco de negócio a migrations, escrita
acidental e acoplamento de schema.

Na versão de 2026-09-14 a garantia era topológica: o banco da aplicação
ficava num Postgres próprio (Railway) e `config/env.py` recusava subir com
host `*.rds.amazonaws.com`. No deploy (Fase 9) o Jarvis foi para a
infraestrutura do Cockpit, onde cada aplicação é um schema no database
`easelabs` do `cockpit-prod-db` — `cockpit`, `trade_fv`, `app_api`,
`app_pipelines` e agora `jarvis`. A trava por nome de host passou a barrar
exatamente a configuração correta, e já protegia menos do que prometia:
pelo túnel SSM o host é `127.0.0.1`, e o `migrate` de produção rodou sem
ela disparar.

## Decisão
- **Banco da aplicação:** schema `jarvis` no database `easelabs`, fonte de
  verdade das conversas e da auditoria, gerido por migrations do Django.
  Configurado por `APP_DATABASE_URL` (ou `APP_DB_*`); em desenvolvimento
  continua o Postgres local do `docker-compose.yml`.
- **Banco de negócio:** acessado exclusivamente pelo
  `PostgresReadOnlyExecutor` (`datasource/executors/`) com conexão psycopg2
  explícita, configurada por `ANALYTICS_DATABASE_URL`, com a role de
  leitura (ADR-0008).

O banco de negócio continua **fora** de `DATABASES` do Django: sem alias,
sem router, sem ORM. O único ponto de entrada é o executor.

A separação agora é garantida pelo banco, não pela topologia
(`infra/app-db/02_criar_schema_jarvis.sql`):

- a role `jarvis_app` é dona só do schema `jarvis`, com `search_path`
  fixado nela, sem `CREATE` em `public` nem `CREATEDB`;
- ela não tem `USAGE` nos schemas de negócio — conectado como a aplicação,
  `CREATE TABLE public.…` e `SELECT … FROM cddd.…` dão `permission denied`
  (conferido em 2026-09-21);
- `config/env.py` repete o `search_path=jarvis` nas `OPTIONS` da conexão
  quando o host é de RDS, ou quando `APP_DB_SCHEMA` é informado (caso do
  túnel, em que o host não denuncia o RDS).

## Consequências
- Testes nunca dependem do RDS: usam `FakeQueryExecutor` ou o
  `analytics_db` sintético local do `docker-compose.yml`.
- **A trava por host mudou de lugar:** vale só para a suíte de testes.
  `config.settings_test` chama `database_from_env(..., para_testes=True)`,
  que recusa host de RDS — o pytest-django cria e apaga bancos `test_*` no
  servidor configurado, e isso nunca pode acontecer no `cockpit-prod-db`.
- Os resultados de consulta ficam registrados no banco da aplicação
  (`QueryRun`), com amostra limitada, para auditoria.
- **Prefixo `APP_` nas variáveis do banco da aplicação** (Fase 1): o
  `bi/.env` já existia com credenciais da AWS, e nomes genéricos
  (`DATABASE_URL`, `POSTGRES_HOST`) poderiam apontar para o RDS de negócio.
- O `migrate` não roda no start do container: é uma task avulsa do ECS,
  precedida de snapshot manual do RDS (Fase 9, passo 10), porque o database
  é compartilhado com o Cockpit.
- A suíte de testes usa `config.settings_test`, que não carrega o `.env` e
  aponta sempre para o Postgres local.
