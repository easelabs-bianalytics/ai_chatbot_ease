# SPEC do MVP

> Primeira entrega funcional do chatbot de BI. Em caso de conflito de escopo
> com `SPEC.md`, este documento prevalece para o MVP.

## 1. Objetivo

Demonstrar, em ambiente controlado, que o sistema consegue:

1. receber uma pergunta de um usuário autenticado pelo chat web;
2. escrever a consulta SQL que responde a pergunta, partindo das consultas
   validadas de `chatbot_bi_referencia_querys.md` e priorizando sempre a
   consulta mais simples e organizada (ADR-0014);
3. validar e executar a consulta com segurança (somente leitura, limite de
   tempo e linhas);
4. responder com números que existem no resultado, mostrando a consulta
   executada;
5. dizer que não sabe quando não souber onde está o dado ou não houver dado;
6. registrar tudo para auditoria e apresentar um relatório de uso.

## 2. Limites obrigatórios

O MVP deve ser:

- single-tenant (Ease Labs);
- somente leitura no banco de negócio;
- restrito aos schemas e tabelas permitidos no catálogo, com colunas
  pessoais bloqueadas;
- orientado pelas consultas de referência: quando uma referência responde ou
  está próxima da pergunta, ela é a base da consulta gerada;
- testável inteiramente com fakes e com um banco analítico sintético local.

Ficam fora do MVP:

- cálculos feitos pelo modelo no texto da resposta (total, share, variação e
  média são calculados na própria consulta SQL);
- gráficos, exportação de planilha e dashboards;
- SSO (login do próprio Django no MVP);
- múltiplos canais (só chat web);
- escrita de qualquer tipo no banco de negócio.

## 3. Fluxo mínimo

```text
Pergunta no chat
    -> autenticação e deduplicação (client_message_id)
    -> registro da mensagem, enfileiramento
    -> regras determinísticas
    -> planejamento pela IA (SQL + referência usada como base)
    -> validação da consulta (sql_guard)
    -> execução somente leitura
       (erro do validador ou do banco -> uma correção pela IA com o erro)
    -> redação pela IA
    -> checagem numérica
    -> registro (SQL, tokens, custo, latência, decisão)
    -> resposta com a consulta visível no chat
```

## 4. Requisitos do MVP

### PM-01 — Chat web autenticado
Login do Django. Usuário vê e continua apenas as próprias conversas.

### PM-02 — Idempotência
Uma mensagem com o mesmo `client_message_id` não é processada nem
respondida duas vezes.

### PM-03 — Persistência
Conversa, mensagens (entrada e saída), status do processamento e
timestamps.

### PM-04 — Planejamento estruturado
Contrato de planejamento de `SPEC.md` 10.1, validado por JSON schema: SQL
completo, `reference_query_id` da consulta de referência usada como base (ou
nulo) e motivo da decisão. O prompt de planejamento obriga a:

- procurar primeiro a referência que responde ou mais se aproxima da
  pergunta e partir dela;
- seguir as regras de negócio das referências (tabelas tratadas, filtros de
  venda, normalização de CNPJ/CRM, colunas com aspas);
- escrever a consulta mais simples e organizada possível: menos tabelas e
  JOINs, colunas explícitas, no mesmo estilo das referências.

### PM-05 — Execução segura
Toda consulta passa pelo `sql_guard`: um único statement `SELECT`/`WITH`,
só schemas e tabelas permitidos, colunas bloqueadas recusadas, sem
`SELECT *` em tabela com coluna bloqueada, sem funções perigosas nem
catálogos do sistema. Execução em transação READ ONLY, com
`statement_timeout` e limite de linhas; truncamento sinalizado.

### PM-06 — Correção única
Se o `sql_guard` reprovar ou o banco devolver erro (coluna inexistente,
sintaxe, tipo, timeout), a IA recebe a mensagem de erro e reescreve a
consulta uma vez. Persistindo o erro: resposta legível e lacuna registrada.

### PM-07 — Não inventar
Sem saber onde está o dado: resposta "não sei" explícita e registro de
lacuna. Resultado vazio: informado como resultado vazio.

### PM-08 — Ancoragem numérica
Todo número da resposta deve existir no resultado, na pergunta ou em
literais de filtro da consulta. Falhou: uma reescrita; falhou de novo:
resposta com a tabela sem narrativa.

### PM-09 — Fonte visível
Toda resposta com dado mostra o SQL executado (recolhível), a referência
usada como base, o momento da execução e se houve truncamento.

### PM-10 — Falhas legíveis
Falha da IA (após retry) ou do banco (após a correção única) gera mensagem
clara ao usuário e registro com o erro.

### PM-11 — Auditoria no Admin
`AIReply` com `AICall` e `QueryRun` aninhados; filtros por decisão, status
e referência usada.

### PM-12 — Chat local
`chat_local` conversa pelo pipeline real no terminal, com `--fake-ai`,
`--fake-db` e `/sql` para ver as consultas geradas.

### PM-13 — Validação
`run_synthetic_cases` executa os casos da seção 5 contra a IA real e gera
`docs/validation-report.md`.

### PM-14 — Relatório
`bi_report` com perguntas, taxa de resposta, "não sei", esclarecimentos,
consultas executadas e falhas, correções, timeouts, uso das referências,
latência, tokens, custo e principais lacunas.

## 5. Validação mínima

Casos sintéticos cobrindo:

- pergunta coberta por uma referência: a consulta gerada parte dela e o
  resultado é igual ao da referência no banco sintético;
- pergunta que exige variação de uma referência (outro filtro, agrupamento
  ou período): SQL simples, correto e baseado na referência (revisão
  manual);
- pergunta que exige cálculo (share, variação, total): cálculo feito no SQL;
- uso de tabela desaconselhada nas referências (ex.: `cddd.fato_cdd`): não
  deve ocorrer;
- pergunta sobre dado que não existe no banco conhecido;
- pergunta ambígua (sem período, sem médico/PDV);
- pedido de alteração de dados;
- injeção de prompt e de SQL;
- tentativa de obter coluna pessoal bloqueada;
- erro do banco corrigido na segunda tentativa;
- mensagem duplicada;
- falha do provedor de IA;
- timeout do banco;
- resposta com número sem suporte no resultado;
- resultado vazio e resultado truncado.

Para cada caso: comportamento esperado, obtido, aprovado/reprovado/revisão
manual e motivo. Alucinação numérica, escrita no banco, coluna bloqueada e
duplicidade são bloqueadores.

## 6. Requisitos não funcionais mínimos

- credenciais somente em variáveis de ambiente, documentadas em `.env.example`;
- timeout na chamada à IA e na consulta;
- tratamento legível de falhas externas;
- testes dos fluxos críticos sem dependência de serviço externo;
- migrations reproduzíveis;
- instruções de execução local atualizadas.

## 7. Critérios de aceite

1. Uma pergunta de teste percorre o fluxo completo sem edição manual no banco.
2. Pergunta coberta por referência retorna o mesmo resultado da consulta de
   referência.
3. Pergunta sem dado conhecido retorna "não sei" e gera lacuna.
4. Nenhum pedido de escrita e nenhuma coluna bloqueada chega ao banco.
5. Mensagens duplicadas não geram respostas duplicadas.
6. SQL executado, tokens, custo e latência ficam registrados.
7. O relatório pode ser apresentado.
8. Os testes críticos passam.
9. Outra pessoa consegue rodar o projeto seguindo o README.
