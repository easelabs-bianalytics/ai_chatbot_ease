# Onboarding — Chatbot de BI da Ease Labs

> Documento de continuidade do projeto. Primeira versão escrita em
> 2026-09-14, no fim da Fase 1, e atualizada a cada fase. Leia este arquivo
> primeiro e depois os documentos citados, conforme a necessidade.

## 1. Status

- **Fases concluídas:** 0 (decisões), 1 (fundação) e 2 (modelos, canal e API
  do chat).
- **Existe hoje:** projeto Django configurado, healthcheck, infraestrutura
  local (Postgres, Redis e banco analítico sintético com usuário de leitura),
  Docker/Railway, a API do chat com idempotência e isolamento por usuário, os
  modelos de auditoria e o Admin.
- **Ainda não existe:** IA, catálogo e executor de consultas (Fases 3 a 5). A
  API aceita a pergunta e a registra, mas ninguém responde ainda — o
  enfileiramento entra na Fase 4, no ponto marcado em `messaging/views.py`.
- **Bloqueios externos:** usuário de leitura no RDS (D-01), rede Railway → RDS
  (D-02) e chave da OpenAI (D-03). Ver `docs/open-decisions.md`.

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
│   ├── ai_orchestrator/       # AIReply, AICall, CatalogGap + prompts/planner_v1.md
│   └── datasource/            # QueryRun (cada tentativa de consulta)
├── infra/analytics_db/init/   # cria o usuário de leitura do banco sintético
├── tests/ conftest.py · unit/ · integration/
├── docs/ adr/ · plan.md · open-decisions.md · catalog-checklist.md
├── docker-compose.yml · Dockerfile · railway.json · pyproject.toml · uv.lock
└── .env.example
```

Faltam os apps `catalog` e `reporting`, e os módulos de orquestração
(`rules`, `grounding`, `providers`, `tasks`) dentro de `ai_orchestrator`. A
estrutura completa planejada está no `CLAUDE.md`.

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
  (ADR-0010). Isso começa a virar código na Fase 3.

## 6. Cuidados ao continuar

- Nunca ler, imprimir ou commitar o `bi/.env`.
- Rodar `uv run pytest` antes de todo commit; commitar só se passar, e só
  quando pedido. Mensagens em português, explicando o porquê, sem
  `Co-Authored-By`.
- Nada que dependa de item aberto em `docs/open-decisions.md` é implementado
  antes da resolução.
- Não conectar ao RDS nem à OpenAI sem autorização explícita.
