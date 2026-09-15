# Plano de execução

> Atualizado a cada fase concluída. Pendências externas em
> `docs/open-decisions.md`; decisões arquiteturais em `docs/adr/`.

Legenda: ✅ concluída · 🔲 não iniciada · ⏳ bloqueada por dependência externa

Toda fase termina com a suíte de testes passando e o resultado mostrado.
Commit só quando pedido.

## Fase 0 — Descoberta e decisões
**Status: ✅ concluída (2026-09-14)**

- [x] Estudo do projeto de referência `avaliacao_eleitores` (somente leitura)
- [x] Mapa "o que existe lá → o que vira aqui" aprovado
- [x] `git init` em `bi/`, `.gitignore`
- [x] `CLAUDE.md` com regras de trabalho e estrutura aprovada
- [x] `SPEC.md` e `SPEC_PILOT.md`
- [x] ADR-0001 a ADR-0013
- [x] `docs/open-decisions.md`, `docs/catalog-checklist.md`
- [x] Revisão: SQL gerado pela IA com as consultas validadas como referência (ADR-0014, substitui ADR-0009)
- [x] Rascunho do prompt de planejamento (`app/ai_orchestrator/prompts/planner_v1.md`)
- [x] Plano de testes (final deste documento)

## Fase 1 — Fundação
**Status: ✅ concluída (2026-09-14)**

- [x] `pyproject.toml` com uv, Python 3.12 (Django 5.2 LTS, DRF, Celery[redis], gunicorn, whitenoise, psycopg2-binary, python-dotenv, openai, sqlglot, PyYAML; dev: pytest, pytest-django) e `uv.lock`
- [x] Projeto Django em `app/config` (settings por variável de ambiente, proxy SSL, CSRF, Celery com `acks_late`)
- [x] **Banco da aplicação só lê `APP_*`** e recusa subir apontando para `*.rds.amazonaws.com` (`config/env.py`, ADR-0002) — o `bi/.env` já tinha credenciais da AWS com nomes desconhecidos
- [x] `config.settings_test`: suíte não carrega o `.env` e usa sempre o Postgres local
- [x] DRF com `SessionAuthentication` e `IsAuthenticated` por padrão
- [x] `docker-compose.yml`: `db` (5434), `redis` (6381), `analytics_db` (5435, sintético, com usuário `bi_readonly`) — portas fora das da referência
- [x] Usuário de leitura do banco sintético validado: `CREATE TABLE` recusado pelo próprio Postgres
- [x] `/api/health/` aberto e sem tocar o banco
- [x] `tests/conftest.py` com fixtures autouse (Celery eager, remoção de credenciais reais, bloqueio do cliente OpenAI)
- [x] Migrations aplicando, revertendo e reaplicando no banco local
- [x] `Dockerfile`, `railway.json`, `.env.example`, `.dockerignore`, `.gitattributes`
- [x] `README.md` e primeira versão do `ONBOARDING.md`
- [x] 24 testes automatizados passando

## Fase 2 — Modelos, canal e API do chat
**Status: 🔲**

- [ ] Apps `conversations`, `messaging`, `ai_orchestrator` (modelos), `datasource` (modelos)
- [ ] `Conversation`, `Message` (`client_message_id` único), `AIReply`, `AICall`, `QueryRun`, `CatalogGap`
- [ ] `Channel` + `FakeChannel` + `WebChannel`; `services.py` de ingestão idempotente
- [ ] API: criar conversa, enviar mensagem (`202`), polling; só conversas do próprio usuário
- [ ] Admin com inlines e filtros
- [ ] Testes: idempotência, isolamento entre usuários, login obrigatório

## Fase 3 — Catálogo e acesso ao banco
**Status: 🔲** (executor real ⏳ D-01)

- [ ] `knowledge/catalog.yaml`: schemas e tabelas permitidos, colunas bloqueadas, dicionário
- [ ] Loader de referências + catálogo; `catalog_hash`; toda referência Q01–Q51 parseável e aprovada pelo `sql_guard`
- [ ] `sql_guard` (sqlglot): statement único, SELECT/WITH, DML/DDL em qualquer nó, schemas/tabelas permitidos, catálogos do sistema, colunas bloqueadas, `SELECT *` em tabela com coluna bloqueada, funções perigosas, `FOR UPDATE`, LIMIT
- [ ] `QueryExecutor` + `FakeQueryExecutor` + `PostgresReadOnlyExecutor`
- [ ] Schema sintético no `analytics_db` espelhando as tabelas das referências, com dados que permitem conferir Q01–Q51
- [ ] Comando de snapshot do schema real (⏳ D-01)
- [ ] Teste de integração: escrita recusada pelo próprio banco; timeout; truncamento
- [ ] Comando `catalog_check`

## Fase 4 — Orquestrador com fakes
**Status: 🔲**

- [ ] `rules.py`: pedido de escrita, ajuda, mensagem inválida
- [ ] Pipeline: idempotência → regras → planejamento (SQL) → `sql_guard` → execução → redação → `grounding.py` → registro
- [ ] Correção única da consulta com o erro do guard ou do banco; reescrita única da resposta com fallback em tabela
- [ ] "Não sei" com `CatalogGap`; resultado vazio; falha da IA; falha do banco
- [ ] Histórico da conversa para perguntas de seguimento (`AI_HISTORY_MAX_MESSAGES`)
- [ ] `tasks.py` (Celery) e `FakeAIProvider`
- [ ] Providers programáveis em `tests/fakes/`, testes com docstring do incidente prevenido

## Fase 5 — Provider real e chat local
**Status: 🔲** (⏳ D-03)

- [ ] `OpenAIProvider` (GPT-4o, Structured Outputs, custo com cache) e `RetryingAIProvider`
- [ ] `prompts/planner_v1.md` (rascunho da Fase 0) ligado ao provider, com referências, catálogo, schema e data de hoje injetados; `prompts/answerer_v1.md`
- [ ] `provider_factory`
- [ ] `chat_local` (`--fake-ai`, `--fake-db`, `/nova`, `/sql`, `/status`, `/sair`)

## Fase 6 — Interface web
**Status: 🔲**

- [ ] Login, lista de conversas, chat com polling
- [ ] Fonte da resposta visível (SQL executado, referência usada, momento, truncamento)

## Fase 7 — Validação
**Status: 🔲** (⏳ D-03, D-04)

- [ ] `run_synthetic_cases` com as categorias do `SPEC_PILOT.md` seção 5
- [ ] Casos cobertos por referência comparam o resultado da consulta da IA com o da referência no banco sintético
- [ ] `docs/validation-report.md` com prompt, hash do catálogo e data no cabeçalho

## Fase 8 — Relatório
**Status: 🔲**

- [ ] `reporting/services.py` + `bi_report` (terminal e `--csv`)

## Fase 9 — Deploy
**Status: 🔲** (⏳ D-01, D-02)

- [ ] Railway: Postgres, Redis, `web`, `worker`
- [ ] Conexão com o RDS validada com usuário de leitura

---

## Plano de testes

Regra geral: a suíte (`uv run pytest`) nunca acessa rede, OpenAI ou o RDS.
`tests/conftest.py` remove `AI_PROVIDER_API_KEY` e `ANALYTICS_DATABASE_URL`
do ambiente por fixture autouse, então valores do `bi/.env` nunca chegam aos
testes. Cada teste traz na docstring o incidente que previne.

| Camada | O que prova | Tipo |
|---|---|---|
| `sql_guard` | Escrita, DDL, múltiplos statements, CTE com DML, catálogos do sistema, colunas bloqueadas em qualquer posição, `SELECT *` em tabela sensível, funções perigosas, `FOR UPDATE`, LIMIT e truncamento | unit |
| Referências | Q01–Q51 parseáveis e aprovadas pelo `sql_guard` | unit |
| `grounding.py` | Formatos pt-BR/en, percentuais, milhares; literal no `SELECT` não ancora número | unit |
| `rules.py` | Pedido de escrita, ajuda, mensagem inválida sem chamar o modelo | unit |
| Orquestrador | Cada ramo com providers programáveis e `FakeQueryExecutor`: resposta, esclarecimento, não sei, vazio, truncado, correção única, falha da IA, falha do banco, idempotência | unit |
| `OpenAIProvider` | Contratos JSON, erro de API, JSON inválido, custo com cache (cliente mockado) | unit |
| `RetryingAIProvider` e tarefa Celery | Backoff, esgotamento, execução eager | unit |
| API do chat | Login obrigatório, isolamento entre usuários, idempotência (`202` → `200`) | integration |
| `PostgresReadOnlyExecutor` | Contra o `analytics_db` local com usuário de leitura: escrita recusada pelo próprio banco, timeout, truncamento | integration |
| `run_synthetic_cases` | Comportamento com a IA real | fora da suíte, gera relatório |
