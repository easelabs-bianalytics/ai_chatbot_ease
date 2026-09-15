# ADR-0003: Celery + Redis para processamento assíncrono

## Status
Aceito — 2026-09-14

## Contexto
Responder uma pergunta envolve até duas ou três chamadas ao modelo
(planejamento, redação, eventual reescrita) e uma consulta ao RDS com
timeout próprio. Somado ao retry com backoff, o tempo pode passar do que é
razoável segurar numa requisição HTTP do gunicorn. O projeto de referência
chegou à mesma arquitetura (lá, ADR-0010) depois de começar síncrono.

## Decisão
A API do chat apenas autentica, valida, persiste a mensagem de forma
idempotente e enfileira `ai_orchestrator.tasks.process_message`,
respondendo `202 Accepted`. O navegador consulta as novas mensagens da
conversa (ADR-0007). Redis é broker e result backend.

Configuração herdada da referência, pelos mesmos motivos:
`CELERY_TASK_ACKS_LATE=True`, `CELERY_TASK_REJECT_ON_WORKER_LOST=True`,
`CELERY_WORKER_PREFETCH_MULTIPLIER=1`, e orquestrador idempotente (se já
existe `AIReply` para a mensagem, devolve sem reprocessar).

## Consequências
- Rodar a aplicação exige processo worker além do web.
- Testes rodam com `CELERY_TASK_ALWAYS_EAGER=True` via `tests/conftest.py`,
  sem Redis.
- Janela residual aceita: worker cair entre gravar a mensagem de saída e o
  `AIReply` pode duplicar uma resposta — raro, e preferível a pergunta sem
  resposta.
