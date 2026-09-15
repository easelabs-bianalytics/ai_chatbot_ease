# ADR-0006: Prompt e catálogo de dados versionados em arquivo

## Status
Aceito — 2026-09-14. Formato do catálogo revisado no mesmo dia pelo
ADR-0014.

## Contexto
O comportamento da IA depende de dois insumos que mudam com frequência e
precisam de revisão: as instruções do modelo e o catálogo de dados
(consultas aprovadas, parâmetros, colunas e definições de negócio). O time
de BI já mantém as consultas validadas em
`chatbot_bi_referencia_querys.md`. Na referência, prompt e conhecimento em
arquivo no Git funcionaram bem (lá, ADR-0008).

## Decisão
- Prompts em `app/ai_orchestrator/prompts/`: `planner_v1.md` e
  `answerer_v1.md`, com `PROMPT_VERSION_TAG` em `prompts.py`.
- **Consultas de referência:** `chatbot_bi_referencia_querys.md`, mantido
  pelo time de BI, é injetado inteiro no prompt de planejamento como norte
  da IA (ADR-0014). Não é migrado para outro formato: um só arquivo, sem
  cópia para divergir.
- **Catálogo:** `app/knowledge/catalog.yaml` com o que precisa ser lido por
  máquina: schemas e tabelas permitidos, colunas bloqueadas e dicionário de
  colunas além das citadas nas referências. YAML porque o `sql_guard` lê
  essa estrutura.
- **Snapshot do schema:** gerado a partir do RDS por comando, com o usuário
  de leitura (depois de D-01), para a IA conhecer as colunas reais e não
  chutar nomes.
- Cada `AIReply` grava `prompt_version` e `catalog_hash` (SHA-256 de
  referências + catálogo + snapshot).

## Consequências
- Mudança de prompt ou catálogo é commit revisável; o relatório de
  validação registra as versões com que foi gerado, para ficar evidente
  quando está obsoleto.
- Não há tabelas `PromptVersion`/`CatalogEntry` no MVP.
- O loader valida na carga (YAML bem formado, cada consulta de referência
  parseável e aprovada pelo `sql_guard`) e falha alto se algo estiver
  inválido.
