# ADR-0008: Acesso somente leitura ao banco de negócio, em três camadas

## Status
Aceito — 2026-09-14. Camada de aplicação revisada no mesmo dia pelo
ADR-0014 (SQL gerado pela IA).

## Contexto
A IA escolhe o que consultar a partir de texto livre de usuários. Uma única
camada de proteção (só prompt, só parser ou só permissão do banco) não é
suficiente: prompt é contornável, parser pode ter lacuna e permissão pode
ser configurada errado. O RDS atende outros sistemas; uma consulta pesada
ou uma escrita teria impacto fora do chatbot.

## Decisão
Defesa em profundidade, qualquer camada sozinha bloqueia:

1. **Banco:** usuário dedicado com `GRANT SELECT` apenas nos schemas e
   objetos do catálogo (`audit`, `cddd`, `estoque_redes`,
   `ruptura_extrato`, `pbm`, `tdd` — lista final no catálogo), sem
   permissão de escrita ou DDL. Conexão com `sslmode=require`.
2. **Sessão:** toda execução abre transação `READ ONLY`, aplica
   `SET LOCAL statement_timeout` (`ANALYTICS_STATEMENT_TIMEOUT_MS`) e
   termina em rollback.
3. **Aplicação (`datasource/sql_guard.py`, sqlglot, dialeto postgres).**
   Com o SQL gerado pela IA (ADR-0014), esta é a principal barreira da
   aplicação. A validação é feita sobre a árvore sintática inteira, não
   sobre o texto:
   - um único statement, só `SELECT`/`WITH`; qualquer nó de escrita ou DDL
     em qualquer ponto da árvore (inclusive CTE com `DELETE`) reprova;
   - apenas schemas e tabelas permitidos no catálogo; `pg_catalog`,
     `information_schema` e demais catálogos do sistema recusados;
   - colunas bloqueadas recusadas mesmo que o banco permita, em qualquer
     posição (seleção, filtro, junção, ordenação);
   - `SELECT *` recusado em tabela que tenha coluna bloqueada;
   - funções administrativas e perigosas recusadas (`pg_sleep`,
     `pg_read_file`, `pg_ls_dir`, `dblink*`, `lo_*`, `set_config`,
     `pg_terminate_backend`, entre outras); função com schema só dos
     schemas permitidos;
   - cláusulas de trava (`FOR UPDATE`, `FOR SHARE`) recusadas;
   - consulta embrulhada em `SELECT * FROM (...) q LIMIT max+1` para impor
     `ANALYTICS_MAX_ROWS` e detectar truncamento.

**Colunas bloqueadas no MVP:** dados do consumidor em
`pbm.fato_pbm_transacoes` (`CPF_CONS`, `NOME_CONS`, `E_MAIL`, `CELULAR`),
já vetados na referência de consultas, e contatos pessoais de médicos
(`audit.rx_cadastro_mais_recente.email`, `celular`). A lista final está em
`docs/open-decisions.md`.

## Consequências
- Pedido de escrita é recusado já na regra determinística, antes do modelo,
  e ainda seria barrado nas três camadas.
- Timeout e truncamento viram estados registrados em `QueryRun` e
  informados ao usuário.
- O resultado enviado ao modelo é limitado a `AI_MAX_ROWS_TO_MODEL`; o
  truncamento é sinalizado no contexto da redação.
- Um teste de integração contra o `analytics_db` local, com usuário de
  leitura, prova que a escrita é recusada pelo próprio banco.
