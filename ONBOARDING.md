# Onboarding — Chatbot de BI da Ease Labs

> Documento de continuidade do projeto. Primeira versão escrita em
> 2026-09-14, no fim da Fase 1, e atualizada a cada fase. Leia este arquivo
> primeiro e depois os documentos citados, conforme a necessidade.

## 1. Status

- **Fases concluídas:** 0 (decisões), 1 (fundação), 2 (modelos, canal e API
  do chat), 3 (catálogo, validador de SQL e executor somente leitura) e 4
  (orquestrador com fakes).
- **Existe hoje:** projeto Django configurado, healthcheck, infraestrutura
  local (Postgres, Redis e banco analítico sintético com usuário de leitura),
  Docker/Railway, a API do chat com idempotência e isolamento por usuário, os
  modelos de auditoria e o Admin.
- **O chat já responde de ponta a ponta** com o provedor fake e o banco
  sintético: a API enfileira, o orquestrador planeja, valida, executa,
  redige, confere os números e registra tudo.
- **Suíte de validação pronta** (Fase 7): `app/knowledge/casos_validacao.yaml`
  tem 127 casos derivados do `chatbot_bi_referencia_querys.md`, com gabarito
  montado da própria consulta do documento. `run_synthetic_cases --so-gabarito`
  confere os gabaritos no banco sem chamar a IA.
- **A IA real está ligada** (Fase 5): `gpt-5.6-terra` escreve a consulta e
  `gpt-5.6-luna` redige (ADR-0016). Converse com ela por
  `manage.py chat_local`; o contexto vai recortado por tema (ADR-0015) e há
  teto de gasto mensal (`AI_MONTHLY_BUDGET_USD`).
- **A interface web está pronta** (Fase 6, ADR-0017). Para rodar local:
  túnel do RDS aberto, `DEBUG=1` no processo, um worker do Celery
  (`cd app && DEBUG=1 uv run celery -A config worker -P solo`) e
  `DEBUG=1 uv run python app/manage.py runserver`. O login usa os usuários
  do Django (`manage.py createsuperuser`).
- **Ainda não existe:** a rodada completa da suíte (Fase 7) e o relatório
  (Fase 8). Até lá, quem responde é o `FakeAIProvider`, que casa a pergunta
  com o título das consultas de referência e não entende pergunta de
  verdade.
- **Acesso ao banco real:** a role `bi_chatbot_ro` lê os 6 schemas do documento
  de referência. Em desenvolvimento o acesso é pelo túnel SSM, que sobe só no
  WSL (`infra/rds/abrir_tunel_wsl.sh`); conecte em `127.0.0.1:15432`.
- **Pendências externas:** rede da aplicação no ECS até o RDS (D-02) e o schema
  de metas (`remuneracao_fv`). Ver `docs/open-decisions.md`.

## 2. Documentos-chave (nesta ordem)

| Arquivo | Para que serve |
|---|---|
| `CLAUDE.md` | Regras de trabalho e estrutura aprovada — inegociáveis |
| `README.md` | Como rodar, testar e fazer deploy |
| `SPEC_PILOT.md` | Escopo e critérios de aceite do MVP (prevalece) |
| `SPEC.md` | Visão completa do produto |
| `docs/plan.md` | Progresso fase a fase e plano de testes |
| `docs/open-decisions.md` | Pendências externas e decisões ainda não tomadas |
| `docs/adr/` | Decisões arquiteturais (0001–0014; a 0009 foi substituída pela 0014) |
| `chatbot_bi_referencia_querys.md` | Consultas validadas pelo time de BI: o norte da IA |
| `docs/catalog-checklist.md` | O que o time de BI ainda precisa entregar |

## 3. Origem do projeto

A estrutura e o jeito de trabalhar replicam
`D:\projetos_rubens\avaliacao_eleitores`, uma IA de atendimento pelo WhatsApp
que já roda em produção. **Esse diretório é somente leitura.** Vale consultar
para ver padrões (interfaces com fake, pipeline do orquestrador, casos
sintéticos, testes com a docstring do incidente), nunca para copiar o domínio.

## 4. Estrutura

```
bi/
├── app/
│   ├── manage.py
│   ├── config/
│   │   ├── settings.py        # tudo por variável de ambiente
│   │   ├── settings_test.py   # suíte: sem .env, banco local, Celery eager
│   │   ├── env.py             # leitura do ambiente + trava contra o RDS
│   │   ├── celery.py · urls.py · views.py (health) · wsgi.py · asgi.py
│   ├── conversations/         # Conversation (thread de um usuário)
│   ├── messaging/             # Message, channels/{base,web,fake}, services, API
│   ├── ai_orchestrator/       # orchestrator, rules, grounding, canned, tasks,
│   │                          # providers/{base,fake}, prompts/, modelos de auditoria
│   ├── datasource/            # QueryRun, sql_guard, executors/{base,fake,postgres_readonly}
│   ├── catalog/               # loader do catálogo + comando catalog_check
│   └── knowledge/             # catalog.yaml (schemas, bloqueios, limites) + schema_snapshot.md
├── infra/analytics_db/init/   # banco sintético local (schema, dados, usuário de leitura)
├── infra/rds/                 # túnel SSM (WSL) e scripts do usuário de leitura no RDS
├── tests/ conftest.py · unit/ · integration/
├── docs/ adr/ · plan.md · open-decisions.md · catalog-checklist.md
├── docker-compose.yml · Dockerfile · railway.json · pyproject.toml · uv.lock
└── .env.example
```

Falta o app `reporting` e os módulos de orquestração (`rules`, `grounding`,
`providers`, `tasks`) dentro de `ai_orchestrator`. A estrutura completa
planejada está no `CLAUDE.md`.

## 5. Decisões que valem entender antes de mexer no código

- **Dois bancos (ADR-0002).** O Postgres da aplicação guarda conversas e
  auditoria. O RDS da AWS é o banco de negócio: nunca entra em `DATABASES`
  e só será acessado pelo executor somente leitura (Fase 3).
- **Prefixo `APP_` e trava contra o RDS.** O `bi/.env` já existia com
  credenciais da AWS. Para que nenhuma variável genérica (`DATABASE_URL`,
  `POSTGRES_HOST`) faça o `migrate` rodar no banco de negócio, o banco da
  aplicação só lê `APP_*`, e `config/env.py` recusa subir se o host for
  `*.rds.amazonaws.com`.
- **A suíte nunca vê credencial real.** `config.settings_test` não carrega o
  `.env`; `tests/conftest.py` remove as variáveis de IA e do RDS e bloqueia
  a criação de cliente da OpenAI.
- **API fechada por padrão (ADR-0011).** O DRF exige login em toda view que
  não declarar o contrário. Na referência, a ausência dessa configuração
  deixou os webhooks abertos.
- **Idempotência por conversa.** O navegador manda um `client_message_id` por
  pergunta e a unicidade é por conversa, não global: identificador repetido
  entre usuários diferentes não pode cruzar respostas.
- **Conversa alheia responde 404**, e não 403, para não confirmar que ela
  existe.
- **SQL gerado pela IA com as referências como norte (ADR-0014)**, validado
  em três camadas (ADR-0008), e nenhum número sem consulta registrada
  (ADR-0010).
- **`datasource/sql_guard.py` é a barreira principal da aplicação.** Ele
  percorre a árvore sintática inteira, e não o texto: é assim que
  `WITH x AS (DELETE ...)` é pego. O SQL executado é o original, só embrulhado
  no limite de linhas — reemitir da árvore poderia mudar um cast e o número
  junto.
- **A permissão é por schema**, e não tabela a tabela, enquanto D-04 não vem.
  O que protege dado pessoal é a lista de colunas bloqueadas do catálogo, mais
  o GRANT do usuário de leitura no banco.
- **O pipeline tem duas correções únicas, e só duas.** Consulta recusada ou
  com erro volta uma vez para a IA com o motivo; resposta que cita número sem
  suporte volta uma vez com o número acusado. Na segunda falha o sistema para
  de tentar: entrega a tabela crua (o dado existe) ou um aviso legível (não
  existe). Insistir custaria chamadas pagas para o mesmo resultado.
- **"Não sei" vira `CatalogGap`.** É o que transforma a pergunta sem resposta
  em backlog do catálogo, em vez de beco sem saída.

## 6. Cuidados ao continuar

- Nunca ler, imprimir ou commitar o `bi/.env`.
- Rodar `uv run pytest` antes de todo commit; commitar só se passar, e só
  quando pedido. Mensagens em português, explicando o porquê, sem
  `Co-Authored-By`.
- Nada que dependa de item aberto em `docs/open-decisions.md` é implementado
  antes da resolução.
- Não conectar ao RDS nem à OpenAI sem autorização explícita.
