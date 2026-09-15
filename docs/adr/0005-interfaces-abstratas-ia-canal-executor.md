# ADR-0005: Interfaces abstratas para IA, canal e executor de consultas

## Status
Aceito — 2026-09-14

## Contexto
A lógica de negócio (regras, validação, ancoragem numérica, auditoria)
precisa ser testada sem rede, sem custo e sem acesso ao RDS. O projeto de
referência provou o valor desse padrão com IA e canal; aqui há uma terceira
dependência externa: o banco de negócio.

## Decisão
Três interfaces, cada uma com implementação fake criada antes da real:

| Interface | Local | Fake | Real |
|---|---|---|---|
| `AIProvider` | `ai_orchestrator/providers/base.py` | `FakeAIProvider`, `FailingAIProvider` | `OpenAIProvider` (ADR-0013) |
| `Channel` | `messaging/channels/base.py` | `FakeChannel` | `WebChannel` (ADR-0007) |
| `QueryExecutor` | `datasource/executors/base.py` | `FakeQueryExecutor` (resultados, timeout e erro programáveis) | `PostgresReadOnlyExecutor` (ADR-0008) |

O provider real é sempre embrulhado em `RetryingAIProvider` (backoff
exponencial, `AI_PROVIDER_MAX_ATTEMPTS`). Erros nativos (OpenAI, psycopg2)
são traduzidos para `AIProviderError` e `QueryExecutionError`; o
orquestrador só conhece esses contratos.

## Consequências
- Testes usam providers programáveis (`tests/fakes/`) com respostas e
  falhas pré-definidas, em ordem.
- Fakes nunca abrem conexão de rede — `tests/conftest.py` bloqueia a
  criação de cliente real por fixture autouse.
- Trocar de modelo ou de canal não altera o orquestrador.
