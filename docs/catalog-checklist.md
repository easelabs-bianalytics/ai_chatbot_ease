# Checklist do catálogo de dados

O que o time de BI precisa entregar ou confirmar para o chatbot responder
com dados reais. Itens bloqueadores estão ligados a `docs/open-decisions.md`.

## 1. Recebido

- [x] Consultas validadas de referência — `chatbot_bi_referencia_querys.md`
  (2026-09-14): Q01–Q04 prescrição, Q10–Q14 sell-out, Q20–Q23 estoque,
  Q30–Q32 PBM, Q40–Q44 força de vendas e visitas, Q50–Q51 mercado e PDV.
- [x] Regras de negócio embutidas nas consultas (tabela correta de sell-out,
  venda PBM confirmada, UF por CRM, SKUs e EANs).
- [x] Confirmação de que não há dados de paciente no banco.

## 2. Acesso ao banco (bloqueador — D-01, D-02)

- [x] Usuário somente leitura `bi_chatbot_ro` criado e conferido no RDS
  (2026-09-16), com o script `infra/rds/02_criar_usuario_leitura.sql`.
- [x] Donos das tabelas levantados (2026-09-15): `app_pipelines`,
  `cockpit_admin`, `dbt_transform`, `app_eventos`.
- [x] `ruptura_extrato` saiu do documento de referência (O-12 resolvido).
- [ ] Criar `remuneracao_fv` (metas) e conceder leitura à `bi_chatbot_ro`.
- [ ] Security group liberando a origem da aplicação, com SSL.
- [ ] String de conexão entregue fora do Git.

## 3. Para a IA escrever boas consultas

A IA escreve o SQL partindo das referências (ADR-0014). Quanto mais claras
elas forem, mais simples e corretas saem as consultas geradas.

- [ ] Schemas e tabelas que a IA pode consultar, além das citadas nas
  referências.
- [ ] Tabelas que existem mas **não** devem ser usadas, e qual usar no lugar
  (hoje só as tabelas `_stg` do PBM estão bloqueadas).
- [ ] Significado e unidade das colunas mais usadas (ex.: `px1` = volume de
  prescrição; `und` = unidades; `"Cresc_%"` é razão, não percentual).
- [ ] Defasagem de cada fonte (até que data está atualizada).
- [ ] Novas referências para os pedidos frequentes que aparecerem nas lacunas.

## 4. Definições e políticas

- [ ] Colunas pessoais bloqueadas (O-02) e comentários de visitas (O-03).
- [x] Período padrão ou esclarecimento obrigatório (O-04): perguntar, como
  manda o documento de referência.
- [ ] Checagem de custo com `EXPLAIN` antes de executar (O-11).
- [ ] Quem aprova mudanças no catálogo (O-07).
- [ ] Definições de métricas a importar de `memory_bi.md` à medida que
  forem registradas lá.
