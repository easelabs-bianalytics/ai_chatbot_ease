# ADR-0010: Nenhum número sem consulta registrada

## Status
Aceito — 2026-09-14

## Contexto
A regra "se a IA não sabe, não inventa" do projeto de referência, no BI,
tem forma específica: o dano está no número. Um modelo de linguagem arredonda,
soma, estima e completa com plausibilidade — e uma resposta de BI com número
inventado é pior do que nenhuma resposta.

## Decisão
1. Resposta com dado só existe se houver `QueryRun` bem-sucedido na mesma
   resposta. Sem conseguir montar a consulta (dado não localizado nas
   tabelas conhecidas): resposta "não sei" e `CatalogGap`.
2. O modelo não calcula no texto. Somas, médias, variações e percentuais
   são calculados na própria consulta SQL (ADR-0014), para que o número
   venha do banco.
3. **Checagem determinística pós-redação (`ai_orchestrator/grounding.py`):**
   extrai todos os números da resposta (formatos pt-BR e en, percentuais,
   milhares) e exige que cada um exista nos valores do resultado, na
   própria pergunta ou em literais de filtro (`WHERE`, `BETWEEN`) do SQL
   executado, com tolerância apenas de formatação e arredondamento
   declarado. Literal na lista do `SELECT` não conta: senão o modelo poderia
   "ancorar" um número que ele mesmo escreveu na consulta.
4. Reprovou: uma reescrita com o motivo. Reprovou de novo: resposta
   determinística com a tabela do resultado, sem narrativa. Nunca sai o
   texto reprovado.
5. Resultado vazio é resposta própria ("a consulta X rodou para os
   parâmetros Y e não retornou linhas"), distinta de "não sei".
6. Toda resposta com dado exibe a fonte: SQL executado, referência usada
   como base, momento da execução e se houve truncamento.

## Consequências
- Pedido de cálculo derivado (crescimento, share, média) é atendido
  escrevendo o cálculo no SQL, como a Q03 faz com o share.
- O rascunho reprovado fica em `AIReply.raw_response` para auditoria.
- Alucinação numérica é caso bloqueador na suíte de validação.
