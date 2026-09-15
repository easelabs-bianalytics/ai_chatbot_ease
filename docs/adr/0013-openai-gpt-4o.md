# ADR-0013: OpenAI GPT-4o como provedor de IA real

## Status
Aceito — 2026-09-14

## Contexto
Decisão do usuário em 2026-09-14: usar "GPT 4.0" da OpenAI, com a chave
adicionada depois ao `.env`. Interpretado como o modelo `gpt-4o` — ver
confirmação pendente em `docs/open-decisions.md`.

## Decisão
- `OpenAIProvider` (`ai_orchestrator/providers/openai_provider.py`) com
  Structured Outputs (`response_format` `json_schema`, `strict: true`) para
  os contratos de planejamento e redação (`SPEC.md` 10.1 e 10.2).
- `AI_PROVIDER_MODEL` com padrão `gpt-4o`; `AI_PROVIDER_API_KEY` obrigatória
  para uso real; timeout por chamada.
- Erros da API e JSON inválido viram `AIProviderError`.
- Custo estimado por tabela de preço no código, considerando tokens em
  cache (a referência mediu que ignorar o cache quase dobrava a estimativa).
  Valores a confirmar na tabela oficial antes de apresentar custo.
- `provider_factory`: OpenAI quando há chave; fake caso contrário.

## Consequências
- Resultados de consulta (limitados a `AI_MAX_ROWS_TO_MODEL`, sem colunas
  bloqueadas) trafegam para a OpenAI. Confirmado em 2026-09-14 que não há
  dados de paciente no banco.
- Trocar de modelo é mudança de variável; trocar de fornecedor é um novo
  provider contra a mesma interface (ADR-0005).
