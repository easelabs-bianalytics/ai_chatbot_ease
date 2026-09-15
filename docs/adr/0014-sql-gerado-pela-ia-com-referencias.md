# ADR-0014: SQL gerado pela IA, com as consultas validadas como referência (substitui ADR-0009)

## Status
Aceito — 2026-09-14. Substitui ADR-0009.

## Contexto
O ADR-0009 restringia a IA a escolher consultas aprovadas e preencher
parâmetros. Decisão do usuário em 2026-09-14, antes da Fase 1: muitos
pedidos exigem uma consulta que não está pronta (outro filtro, outro
agrupamento, um cruzamento, um cálculo), e limitar a IA ao catálogo deixaria
a maior parte deles sem resposta.

O time de BI mantém `chatbot_bi_referencia_querys.md` com as consultas mais
pedidas e as regras de negócio embutidas nelas. Esse arquivo passa a ser o
norte da IA, não o limite.

O risco que motivou o ADR-0009 continua real: um JOIN ou filtro errado gera
um número plausível e errado. Este ADR muda a forma de mitigá-lo.

## Decisão
1. O planejador devolve o SQL completo, o `reference_query_id` da referência
   usada como base (ou nulo) e o motivo da decisão (`SPEC.md` 10.1).
2. O prompt de planejamento (`app/ai_orchestrator/prompts/planner_v1.md`)
   obriga, nesta ordem:
   - procurar a referência que responde ou mais se aproxima da pergunta e
     partir dela, alterando só o necessário;
   - seguir as regras de negócio das referências (tabela tratada de
     sell-out, venda PBM confirmada, UF por CRM, `tipo = 'PDV'`,
     normalização de CNPJ/CRM/CEP, colunas maiúsculas com aspas);
   - escrever a consulta mais simples e organizada: menos tabelas e JOINs,
     colunas explícitas, aliases curtos, mesmo estilo das referências;
   - fazer cálculos (total, share, variação) na consulta, como a Q03;
   - usar só tabelas e colunas conhecidas; sem saber onde está o dado,
     declarar `unknown`.
3. O contexto do modelo inclui: o arquivo de referências inteiro, o catálogo
   (tabelas permitidas, colunas bloqueadas, dicionário), o snapshot do schema
   quando disponível, a data de hoje (para períodos relativos) e o histórico
   da conversa.
4. Toda consulta passa pelo `sql_guard` (ADR-0008), que passa a ser a
   principal barreira da aplicação.
5. **Correção única:** se o guard reprovar ou o banco devolver erro (coluna
   inexistente, sintaxe, tipo, timeout), o modelo recebe a mensagem de erro
   e reescreve uma vez. Persistindo, resposta legível e `CatalogGap`.

## Consequências
- A cobertura deixa de depender do catálogo; as referências passam a
  garantir qualidade, não a limitar o que se responde.
- **A validação muda:** para perguntas cobertas por referência, os casos
  sintéticos executam a referência e a consulta da IA no banco sintético e
  comparam os resultados. Variações são revisadas manualmente.
  `reference_query_id` permite medir quanto a IA usa as referências.
- Sai a normalização determinística de parâmetros do ADR-0009: a
  normalização de CNPJ, CRM e CEP é feita no SQL, no mesmo padrão das
  referências (`lpad(regexp_replace(...))`).
- O SQL executado fica visível ao usuário e registrado em `QueryRun` (uma
  linha por tentativa); o time de BI revisa amostras no Admin.
- Consulta pesada é um risco maior do que no ADR-0009. Timeout e limite de
  linhas continuam; checagem de custo por `EXPLAIN` antes de executar fica
  em aberto (`docs/open-decisions.md`).
- O `catalog_hash` inclui o arquivo de referências: alterar uma referência
  muda o comportamento da IA e torna obsoleto o relatório de validação.
- Como as referências são injetadas no prompt, o loader valida na carga que
  cada uma é parseável e aprovada pelo `sql_guard` — referência que o guard
  recusaria é bug de catálogo, não da IA.
