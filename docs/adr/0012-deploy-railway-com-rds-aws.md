# ADR-0012: Deploy da aplicação no Railway, banco de negócio na AWS

## Status
Aceito — 2026-09-14

## Contexto
A aplicação segue o padrão de deploy da referência (Railway). O banco de
negócio é o Amazon RDS for PostgreSQL 16.13 na AWS, fora do Railway.

## Decisão
Serviços no Railway:

| Serviço | Observação |
|---|---|
| Postgres (plugin) | Banco da aplicação |
| Redis (plugin) | Broker do Celery |
| `web` | `Dockerfile` da raiz; healthcheck `/api/health/`; `migrate` no start |
| `worker` | Mesma imagem, Custom Start Command `celery -A config worker --loglevel=info`, sem healthcheck |

Configuração por serviço na interface do Railway; `railway.json` só declara
o builder (o Config as Code foi descontinuado em 2026-08-28, conforme a
referência). Produção com gunicorn em `[::]`, WhiteNoise, `collectstatic`
no build, `SECURE_PROXY_SSL_HEADER` e `CSRF_TRUSTED_ORIGINS`.

Conexão Railway → RDS via `ANALYTICS_DATABASE_URL` com `sslmode=require`.

## Consequências
- **Dependência externa:** o RDS precisa aceitar conexões vindas do
  Railway (security group, acessibilidade pública ou alternativa, IP de
  saída). Registrado em `docs/open-decisions.md`; enquanto não resolvido, o
  deploy funciona só com dados sintéticos.
- Se a conectividade Railway → RDS se mostrar inviável, hospedar a aplicação
  na AWS vira um novo ADR, sem mudança de código (tudo por variável de
  ambiente e Docker).
