# ADR-0009: Consultas aprovadas e parametrizadas, sem SQL livre no MVP

## Status
Substituído pelo [ADR-0014](0014-sql-gerado-pela-ia-com-referencias.md) em
2026-09-14, antes da Fase 1. Mantido como registro da decisão original e do
risco que ela tratava (número plausível e errado), que continua valendo e é
mitigado de outra forma no ADR-0014.

## Contexto
Havia duas estratégias:

- **(a)** a IA escolhe uma consulta aprovada do catálogo e preenche
  parâmetros; o código monta e executa;
- **(b)** a IA escreve SQL livre, validado por parser.

No SQL livre, um JOIN ou filtro errado produz um número plausível e
errado — o tipo mais perigoso de invenção, porque passa por dado real. O
time de BI já tem consultas validadas com as regras de negócio embutidas
(ex.: usar `vendas_consolidado` e não `fato_cdd`; venda PBM =
`"STATUS_TRN" = 'CONFIRMADA'`; UF do médico = `left(crm, 2)`).
Decisão do usuário em 2026-09-14: começar por (a).

## Decisão
Cada entrada do catálogo tem: `id` (Q01…), nome, domínio, descrição de
quando usar, exemplos de pergunta, SQL com parâmetros nomeados
(`:data_ini`), parâmetros tipados (`date`, `month`, `crm`, `cnpj`, `cep`,
`int`, `sku`, `ean`, `text`), colunas de saída com significado e unidade, e
notas de regra de negócio.

O modelo devolve `query_id` e `params`. O código:

1. confere que o `query_id` existe;
2. normaliza cada parâmetro deterministicamente (CNPJ → 14 dígitos, CRM →
   UF + 7 dígitos, CEP → 8 dígitos, mês → dia 1, datas ISO) e recusa valor
   inválido com motivo;
3. converte `:nome` para binding do psycopg2;
4. passa pelo `sql_guard` (ADR-0008) mesmo sendo consulta aprovada.

Parâmetro inválido ou ausente gera um replanejamento com o motivo; se
persistir, pedido de esclarecimento ao usuário.

## Consequências
- Pergunta sem consulta correspondente é "não sei" + lacuna registrada,
  que vira backlog do catálogo para o time de BI.
- Cobertura cresce com o catálogo, não com o prompt.
- SQL livre (b) só com novo ADR, depois de a suíte de validação estar
  estável.
