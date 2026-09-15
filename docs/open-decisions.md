# Decisões em aberto

Rastreia decisões que dependem de terceiros ou que ainda não foram tomadas.
Nenhum item vira ADR até estar decidido — ADRs registram só decisões
tomadas (`docs/adr/`).

Regra geral adotada em 2026-09-14: **nenhuma funcionalidade que dependa de
um item desta lista é implementada antes de ele ser resolvido.** Até lá,
usa-se fake ou o banco analítico sintético local.

## Dependências externas

| ID | Dependência | Responsável | Bloqueia | Status |
|---|---|---|---|---|
| D-01 | Usuário somente leitura no RDS com `GRANT SELECT` só nos objetos do catálogo (ADR-0008) | Time de BI / infra AWS | Executor real contra o RDS | Pendente. As credenciais AWS que estão no `.env` não substituem este item: a aplicação usa só a string de conexão de um usuário de leitura (`ANALYTICS_DATABASE_URL`) |
| D-02 | Conectividade Railway → RDS: security group, IP de saída, SSL (ADR-0012) | Infra AWS | Deploy com dados reais | Pendente |
| D-03 | Chave da API OpenAI no `.env` (ADR-0013) | Usuário | Provider real, `chat_local`, casos sintéticos | Pendente — será adicionada |
| D-04 | Catálogo aprovado (schemas/tabelas permitidos, colunas bloqueadas, dicionário), complementando `chatbot_bi_referencia_querys.md` | Time de BI | Validação (Fase 7) | Pendente |
| D-05 | Lista de usuários internos autorizados | Gestão | Go-live | Pendente |

## Decisões de produto e dados

| ID | Pergunta | Proposta | Bloqueia | Status |
|---|---|---|---|---|
| O-01 | "GPT 4.0" é o `gpt-4o`? | `gpt-4o`, configurável por `AI_PROVIDER_MODEL` | Tabela de custo | A confirmar |
| O-02 | Colunas pessoais bloqueadas | Consumidor PBM (`CPF_CONS`, `NOME_CONS`, `E_MAIL`, `CELULAR`) e contato de médico (`rx_cadastro_mais_recente.email`, `celular`). Nome e CRM de médico liberados, como nas consultas de referência | `sql_guard` (Fase 3) | A confirmar |
| O-03 | Comentários livres de visitas (`audit.rx_visitas.comentarios`, Q42) podem ir para o modelo? | Liberar, pois estão na consulta validada | Q42 no catálogo | A confirmar |
| O-04 | Período padrão quando o usuário não informa | Pedir esclarecimento, sem assumir | Planejador (Fase 4) | A confirmar |
| O-05 | Cálculos derivados (crescimento, total, média) | Feitos no SQL, como a Q03 faz com o share; o modelo nunca calcula no texto (ADR-0010, ADR-0014) | — | Decidido em 2026-09-14 |
| O-06 | Limites padrão | `ANALYTICS_STATEMENT_TIMEOUT_MS=15000`, `ANALYTICS_MAX_ROWS=500`, `AI_MAX_ROWS_TO_MODEL=50` | Executor (Fase 3) | A confirmar |
| O-07 | Quem aprova mudanças de catálogo e prompt | Time de BI | Fluxo de mudança | Pendente |
| O-08 | Retenção das conversas e da auditoria | — | Produção | Pendente |
| O-09 | SSO para login | Fora do MVP | Pós-MVP | Pendente |
| O-10 | Formato das consultas de referência | Continuam em `chatbot_bi_referencia_querys.md`, injetado no prompt, sem migração para YAML (ADR-0006, ADR-0014) | — | Decidido em 2026-09-14 |
| O-11 | Checar custo com `EXPLAIN` antes de executar SQL gerado pela IA | Recusar acima de um limite de custo estimado, além do timeout | Executor (Fase 3) | A confirmar |

## Observações operacionais

- O `.env` foi movido para `bi/.env` em 2026-09-14 e contém credenciais
  reais (AWS). Está no `.gitignore`, nunca é lido, impresso ou commitado, e
  os testes não usam seus valores. A chave da OpenAI entra no mesmo arquivo.
