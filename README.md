# Chatbot de BI — Ease Labs

Chat web interno. Um usuário faz uma pergunta de negócio, a IA escreve a
consulta SQL partindo das consultas validadas pelo time de BI
(`chatbot_bi_referencia_querys.md`), executa no banco analítico com usuário
de leitura e responde mostrando a consulta.

Escopo do MVP em `SPEC_PILOT.md` (prevalece), visão completa em `SPEC.md`,
decisões em `docs/adr/`, pendências em `docs/open-decisions.md`, progresso em
`docs/plan.md`. Para continuar o projeto, comece por `ONBOARDING.md`.

## Executando localmente

Pré-requisitos: [uv](https://docs.astral.sh/uv/) e Docker Desktop. O uv
cuida do Python (3.12) e do ambiente virtual.

```bash
# 1. Banco da aplicação, Redis e banco analítico sintético
docker compose up -d db redis analytics_db

# 2. Dependências
uv sync

# 3. Variáveis de ambiente — veja .env.example. Nunca commite o .env.
#    O banco da aplicação só lê variáveis APP_* (ADR-0002).

# 4. Migrations
uv run python app/manage.py migrate

# 5. Servidor
uv run python app/manage.py runserver

# 6. Worker Celery, em outro terminal (usado a partir da Fase 4)
cd app && uv run celery -A config worker --loglevel=info
```

Confira em `http://127.0.0.1:8000/api/health/`. Para entrar no Admin, crie um
usuário com `uv run python app/manage.py createsuperuser`.

## Rodando os testes

```bash
docker compose up -d db analytics_db
uv run pytest -v
```

A suíte usa `config.settings_test`: não carrega o `.env`, aponta sempre para
o Postgres local e bloqueia qualquer cliente real da OpenAI. Nenhum teste
acessa rede, OpenAI ou o RDS.

| Serviço local | Porta |
|---|---|
| Postgres da aplicação (`db`) | 5434 |
| Redis | 6381 |
| Banco analítico sintético (`analytics_db`) | 5435 |

As portas são diferentes das do projeto de referência (5433/6380), que roda
na mesma máquina.

## Deploy (Railway)

Detalhes em `docs/adr/0012-deploy-railway-com-rds-aws.md`. Serviços:
Postgres e Redis (plugins), `web` (este `Dockerfile`, healthcheck
`/api/health/`) e `worker` (mesma imagem, Custom Start Command
`celery -A config worker --loglevel=info`, sem healthcheck).

Variáveis obrigatórias no `web` e no `worker`: `DEBUG=0`, `SECRET_KEY`,
`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` (com `https://`),
`APP_DATABASE_URL=${{Postgres.DATABASE_URL}}`, `REDIS_URL`. A partir das
Fases 3 e 5: `ANALYTICS_DATABASE_URL` (usuário de leitura, D-01) e
`AI_PROVIDER_API_KEY`.

Testar a imagem localmente:

```bash
docker build -t bi-chatbot .
docker run --rm -p 8010:8000 -e PORT=8000 -e DEBUG=0 -e SECRET_KEY=teste \
  -e ALLOWED_HOSTS=localhost,127.0.0.1 \
  -e APP_DATABASE_URL=postgresql://bi_chatbot:bi_chatbot_dev@host.docker.internal:5434/bi_chatbot \
  bi-chatbot
curl http://127.0.0.1:8010/api/health/
```

## Estado atual

Fase 1 (fundação) — ver `docs/plan.md`.
