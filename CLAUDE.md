# CLAUDE.md — Chatbot de BI da Ease Labs

Chatbot web interno: usuários da Ease Labs pedem dados e informações de
negócio e a IA responde consultando o banco analítico (Amazon RDS for
PostgreSQL 16.13, AWS). Leia `SPEC_PILOT.md`, `SPEC.md`, `docs/adr/` e
`docs/open-decisions.md` antes de mexer em qualquer coisa.

## Projeto de referência (SOMENTE LEITURA)

A estrutura e o jeito de trabalhar replicam
`D:\projetos_rubens\avaliacao_eleitores` (IA de atendimento a eleitores via
WhatsApp, em produção). **Estude, nunca altere nada lá.** Replica-se a
estrutura e os padrões, não o domínio: nada de WhatsApp, Evolution API,
respostas prontas do candidato, regras eleitorais, opt-out, tráfego pago,
humanização anti-robô ou atraso de resposta.

## Regras de trabalho (inegociáveis)

- **Commits** em português, humanizados e objetivos, explicando o porquê da
  mudança. **Sem linha `Co-Authored-By`** nem qualquer outra atribuição.
- **Rodar a suíte de testes (`uv run pytest`) antes de todo commit.** Só
  commitar se passar.
- **Não commitar nem dar push sem pedido explícito.**
- Nenhuma funcionalidade que dependa de item aberto em
  `docs/open-decisions.md` é implementada antes de ele ser resolvido.
- Toda decisão de arquitetura vira um ADR numerado em `docs/adr/`.
- Não conectar dados ou serviços reais (RDS, OpenAI) sem autorização
  explícita. Testes automatizados nunca acessam rede.
- Nunca commitar `.env`. Segredos só em variável de ambiente, documentadas
  em `.env.example`. O `bi/.env` contém credenciais reais (AWS): nunca ler,
  imprimir ou logar seu conteúdo, e os testes não usam seus valores.
- Trabalhar em incrementos pequenos: apresentar plano e arquivos antes,
  rodar testes e mostrar resultado depois. `docs/plan.md` é atualizado a
  cada fase.

## Stack

Django + DRF, PostgreSQL (banco da aplicação), Celery + Redis, uv (nunca
pip/requirements.txt), Docker, deploy na AWS ECS (ADR-0012 a substituir),
OpenAI GPT-5.6 Terra para planejar e Luna para redigir, com saída
estruturada (JSON schema) (ADR-0016). Banco de negócio: RDS PostgreSQL, acessado só
com usuário de leitura.

## Estrutura aprovada

```
bi/
├── CLAUDE.md · README.md · ONBOARDING.md · SPEC.md · SPEC_PILOT.md
├── pyproject.toml · uv.lock · Dockerfile · docker-compose.yml · railway.json · .env.example
├── memory_bi.md                     # memória da área (fonte de definições de negócio)
├── chatbot_bi_referencia_querys.md  # consultas validadas: norte da IA, injetadas no prompt
├── app/
│   ├── config/            # settings, celery, urls
│   ├── conversations/     # Conversation = thread de chat de um usuário
│   ├── messaging/         # Message (idempotente), channels/{base,fake,web}, services, API
│   ├── catalog/           # loader e validação do catálogo, comando catalog_check
│   ├── knowledge/catalog.yaml   # schemas/tabelas permitidos, colunas bloqueadas, dicionário
│   ├── knowledge/casos_validacao.yaml  # casos da Fase 7, derivados das referências
│   ├── datasource/        # executors/{base,fake,postgres_readonly}, sql_guard, QueryRun
│   ├── ai_orchestrator/   # orchestrator, rules, grounding, canned, tasks,
│   │                      # providers/{base,fake,openai_provider,retrying}, prompts/*.md,
│   │                      # models (AIReply, AICall), management/commands/chat_local
│   ├── reporting/         # bi_report, run_synthetic_cases
│   └── web/               # página do chat (template, styles.css, app.js, logo) e login por sessão
├── tests/ conftest.py · unit/ · integration/ · fakes/
└── docs/ adr/ · open-decisions.md · plan.md · catalog-checklist.md · validation-report.md
```

## Padrões obrigatórios

- **Interfaces abstratas com implementação fake** (sem rede, sem custo) usada
  nos testes: `AIProvider`, `Channel`, `QueryExecutor` (ADR-0005). Provider
  real sempre embrulhado em `RetryingAIProvider` (backoff exponencial).
- **Pipeline explícito do orquestrador**, uma etapa por módulo — o
  orquestrador só encadeia:
  0. idempotência (já existe `AIReply` para a mensagem → devolve);
  1. regras determinísticas antes do modelo (`rules.py`);
  2. modelo escreve o SQL partindo das consultas de referência e priorizando
     a consulta mais simples e organizada (JSON schema, ADR-0014);
  3. validação determinística da consulta (`sql_guard`); erro do guard ou
     do banco → uma única correção pelo modelo, com a mensagem de erro;
  4. execução somente leitura com limite de linhas e tempo (`QueryRun`);
  5. modelo redige a resposta a partir do resultado (JSON schema);
  6. revisão determinística: todo número citado existe no resultado
     (`grounding.py`);
  7. registro de tudo: tokens, custo, latência, resposta bruta, consulta,
     motivo da decisão — no banco e no Admin.
- **"Se a IA não sabe, não inventa"** (ADR-0010): toda resposta numérica vem
  de uma consulta real registrada em `QueryRun`. Se não souber onde está o
  dado, a IA diz que não sabe e a pergunta vira lacuna do catálogo.
  Cálculos (total, share, variação) são feitos no SQL, nunca no texto.
- **Referências primeiro** (ADR-0014): o prompt de planejamento obriga a
  partir de `chatbot_bi_referencia_querys.md`, seguir suas regras de negócio
  e preferir a consulta mais simples. Mudar esse arquivo muda o
  comportamento da IA e exige rodar `run_synthetic_cases`.
- **Banco de negócio somente leitura** (ADR-0008): usuário de leitura,
  transação READ ONLY, `statement_timeout`, limite de linhas, allowlist de
  schemas e tabelas, colunas pessoais e funções perigosas bloqueadas.
- **Prompt versionado em `.md`** e **catálogo em arquivo**, fora do código
  (ADR-0006). Versão do prompt e hash do catálogo gravados em cada resposta.
- **Idempotência** por `client_message_id` e tarefa Celery com `acks_late`.
- **Falha externa legível**: falha da IA ou do banco vira mensagem clara
  para o usuário e registro auditável, nunca exceção estourando.
- **Testes**: pytest (unit + integration), `conftest.py` com fixtures autouse
  (Celery eager, executor fake, bloqueio de cliente de IA real), providers
  programáveis em `tests/fakes/`, e docstring explicando o incidente que
  cada teste previne.

## Comandos (a partir da Fase 1)

```bash
docker compose up -d db redis analytics_db
uv sync
uv run python app/manage.py migrate
uv run pytest
uv run python app/manage.py chat_local            # provider real, terminal
# chat web local: DEBUG=1 no processo + worker + servidor
(cd app && DEBUG=1 uv run celery -A config worker -P solo)
DEBUG=1 uv run python app/manage.py runserver     # http://127.0.0.1:8000
uv run python app/manage.py run_synthetic_cases --so-gabarito   # só os gabaritos, sem IA
uv run python app/manage.py run_synthetic_cases   # gera docs/validation-report.md
uv run python app/manage.py bi_report
uv run python app/manage.py catalog_check
```
