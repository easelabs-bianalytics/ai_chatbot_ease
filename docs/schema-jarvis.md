# O schema `jarvis`

Onde o Jarvis guarda o que é dele: quem usa, o que perguntou, o que ele
respondeu, como chegou na resposta e quanto custou. Este documento explica
cada tabela para quem vai consultar pelo DBeaver — seja para acompanhar o
uso, investigar uma resposta estranha ou montar, no futuro, uma base de
treino para a IA.

- **Onde:** instância `cockpit-prod-db`, database `easelabs`, schema `jarvis`.
- **Dona das tabelas:** a role `jarvis_app`, que é a da aplicação. Nenhuma
  outra role escreve aqui.
- **Quem lê:** o `rubens_dba` tem `SELECT` em todas as tabelas, inclusive nas
  que forem criadas depois.
- **Quem não lê, de propósito:** o `bi_chatbot_ro`. É sob essa role que roda
  o SQL escrito pela IA; se ela enxergasse este schema, o Jarvis conseguiria
  consultar as perguntas de todo mundo.
- **Horários** ficam em UTC (`timestamptz`). Para ver no horário de
  Brasília: `criado_em AT TIME ZONE 'America/Sao_Paulo'`.

---

## Como as tabelas se ligam

```
auth_user ──┬──< conversations_project
            │         │
            └──< conversations_conversation >── (project_id, opcional)
                      │
                      └──< messaging_message
                              │   direction = 'in'  → a PERGUNTA
                              │   direction = 'out' → a RESPOSTA (in_reply_to_id → a pergunta)
                              │
               pergunta ──1:1── ai_orchestrator_aireply   (a decisão e o custo)
                                      ├──< ai_orchestrator_aicall     (cada chamada ao modelo)
                                      └──< datasource_queryrun        (cada tentativa de SQL)
               pergunta ──< ai_orchestrator_cataloggap                (o que ele não soube)
               resposta ──< datasource_dataexport >── auth_user       (cada planilha baixada)

web_codigodeacesso   (trilha de login; liga ao usuário pelo e-mail)
```

**O ponto que mais confunde:** a resposta não guarda quem perguntou nem a
decisão. O caminho é sempre **pergunta → conversa → usuário**, e a decisão
(`aireply`) pendura na **pergunta**, não na resposta.

---

## As tabelas do produto

### `auth_user` — quem usa o Jarvis

Uma linha por pessoa. É criada no **primeiro acesso** pelo código no e-mail
(ADR-0023); os quatro administradores iniciais foram carregados de
`infra/app-db/usuarios_iniciais.csv`.

| Coluna | O que é |
|---|---|
| `id` | chave usada em todas as outras tabelas |
| `email` | o e-mail `@easelabs.com.br` — é por ele que a pessoa entra |
| `username` | nome interno (`fernando_franco`); não aparece na tela |
| `first_name`, `last_name` | tirados do e-mail no primeiro acesso, editáveis no Admin |
| `is_staff` | "equipe": vê custo e tokens na fonte da resposta e entra no Admin |
| `is_active` | **desmarcado = acesso cortado**, mesmo com e-mail válido |
| `date_joined` | primeiro acesso |
| `last_login` | último acesso |
| `password` | sempre inutilizável (`!…`): ninguém entra por senha |

### `conversations_conversation` — cada conversa

| Coluna | O que é |
|---|---|
| `user_id` | **de quem é a conversa** → `auth_user.id` |
| `title` | o título que aparece na lateral |
| `status` | `open` ou `archived` |
| `project_id` | a pasta em que ela está, ou nulo |
| `position` | ordem escolhida à mão na lateral (0 = nunca arrastada) |
| `deleted_at` | **exclusão lógica**: preenchido quando a pessoa "exclui". Some da tela, mas continua aqui (ADR-0018) |
| `created_at`, `updated_at` | criação e última atividade |

Para contar só o que a pessoa vê na tela: `WHERE deleted_at IS NULL`.

### `conversations_project` — as pastas

| Coluna | O que é |
|---|---|
| `user_id` | dono da pasta |
| `name` | nome da pasta |

### `messaging_message` — perguntas e respostas

É a tabela que tem **o texto de tudo**.

| Coluna | O que é |
|---|---|
| `conversation_id` | a conversa → daí se chega ao usuário |
| `direction` | `in` = pergunta de uma pessoa · `out` = resposta do Jarvis |
| `content` | o texto. Na resposta, é o que apareceu na tela (Markdown) |
| `in_reply_to_id` | só nas respostas: **qual pergunta ela responde** |
| `status` | ciclo de vida: `received` → `processing` → `processed`/`sent`, ou `failed` |
| `client_message_id` | identificador que o navegador manda para uma pergunta não ser processada duas vezes |
| `delivery_detail` | detalhe técnico quando a entrega falha |
| `created_at` | quando foi enviada |

### `ai_orchestrator_aireply` — o que o Jarvis decidiu

Uma linha por pergunta (`message_id` → a pergunta). É o resumo da resposta.

| Coluna | O que é |
|---|---|
| `decision` | `answered` (respondeu com dado) · `empty_result` (consulta sem linhas) · `clarify` (pediu esclarecimento) · `unknown` (não sabe) · `out_of_scope` (fora do escopo) · `conversation` (conversa, sem consulta) · `failed` (falhou) |
| `rule` | preenchido quando a resposta saiu por **regra, sem IA** — ex.: `pedido_de_ajuda`, `ajuste_de_grafico`, `consulta_falhou_duas_vezes` |
| `reply_text` | o texto final da resposta |
| `cost_estimate` | custo em US$ da pergunta inteira (todas as chamadas ao modelo) |
| `tokens_input`, `tokens_output` | tokens somados |
| `latency_ms` | tempo total até a resposta |
| `prompt_version`, `catalog_hash` | versão do prompt e do catálogo usados — permitem saber, meses depois, **com que regras** aquela resposta foi dada |
| `raw_response` | JSON com o que o modelo decidiu (abaixo) |

Chaves de `raw_response`:

| Chave | O que é |
|---|---|
| `reference_query_id` | a consulta de referência em que se baseou (`C20`, `A01`…) |
| `reason` | a justificativa do planejamento |
| `caveats` | ressalvas que a resposta precisou fazer |
| `grafico` | o gráfico escolhido: tipo, eixo X, séries, título |
| `excel` | `true` se a pessoa pediu planilha |
| `sugestoes` | as continuações oferecidas embaixo da resposta |
| `rascunho_reprovado`, `motivos_ancoragem` | quando a primeira redação citou número que não estava no resultado, o rascunho barrado e o porquê (ADR-0010) |

### `ai_orchestrator_aicall` — cada chamada ao modelo

Uma pergunta gera de 1 a ~4 chamadas.

| Coluna | O que é |
|---|---|
| `ai_reply_id` | a decisão a que pertence |
| `stage` | `plan` (escreve o SQL) · `fix` (corrige o SQL, ou relê com o documento inteiro) · `answer` (redige) · `rewrite` (reescreve depois da ancoragem reprovar) |
| `model` | `gpt-5.6-terra` planeja, `gpt-5.6-luna` redige |
| `cost_estimate`, `tokens_input`, `tokens_output`, `latency_ms` | desta chamada |
| `request` | `secoes` do documento enviadas, `contexto_completo`, esforço de raciocínio, `cache_explicito` |
| `response` | `conteudo` (a saída estruturada inteira do modelo), `tokens_em_cache`, `tokens_gravados_no_cache`, `tokens_de_raciocinio` |

### `datasource_queryrun` — cada SQL que a IA escreveu

| Coluna | O que é |
|---|---|
| `ai_reply_id` | a decisão a que pertence |
| `attempt` | 1 = primeira tentativa, 2 = correção |
| `sql` | **o SQL exato** |
| `reference_query_id` | a referência usada |
| `guard_result`, `guard_reason` | se o validador aprovou (`approved`/`rejected`) e, se não, por quê |
| `status` | `success` · `error` · `timeout` · `not_executed` |
| `row_count`, `truncated` | linhas devolvidas e se bateu no limite |
| `error` | a mensagem do banco, quando deu erro |
| `result_sample` | JSON `{columns, rows}` com o resultado — **até 500 linhas de dado de negócio** |

### `ai_orchestrator_cataloggap` — o que ele não soube responder

| Coluna | O que é |
|---|---|
| `message_id` | a pergunta |
| `question`, `reason` | o texto e o motivo |
| `status` | `open` ou `resolved` |

É a lista de trabalho para o documento de referência: pergunta que o Jarvis
não soube é, quase sempre, uma consulta de referência que falta.

### `datasource_dataexport` — cada planilha baixada

| Coluna | O que é |
|---|---|
| `user_id` | quem baixou |
| `message_id` | a resposta da qual saiu |
| `sql`, `row_count`, `truncated` | o que foi exportado |
| `status`, `error` | `ok` ou `error` |

### `web_codigodeacesso` — a trilha de login

Cada pedido de código fica aqui (ADR-0023). Só leitura no Admin.

| Coluna | O que é |
|---|---|
| `email` | quem pediu |
| `criado_em`, `expira_em` | pedido e validade (10 minutos) |
| `usado_em` | preenchido quando a pessoa entrou |
| `anulado_em` | preenchido quando um código mais novo o substituiu ou quando errou 5 vezes |
| `tentativas` | códigos errados digitados |
| `ip`, `navegador` | de onde veio o pedido |
| `codigo_hash` | HMAC do código — o código em si nunca é gravado |

### Tabelas do próprio Django

`auth_group`, `auth_group_permissions`, `auth_permission`,
`auth_user_groups`, `auth_user_user_permissions`, `django_content_type`,
`django_session` (sessões abertas), `django_admin_log` (o que foi mudado no
Admin, e por quem) e `django_migrations` (versão do schema). Não precisam
de consulta no dia a dia.

---

## Consultas prontas

### Quem usa, e quando entrou pela última vez

```sql
SELECT email,
       first_name || ' ' || last_name       AS nome,
       is_staff                             AS equipe,
       is_active                            AS ativo,
       date_joined AT TIME ZONE 'America/Sao_Paulo' AS primeiro_acesso,
       last_login  AT TIME ZONE 'America/Sao_Paulo' AS ultimo_acesso
FROM jarvis.auth_user
ORDER BY last_login DESC NULLS LAST;
```

### Cada pergunta, quem fez e o que o Jarvis respondeu

É a consulta base de tudo — acompanhamento e, no futuro, treino.

```sql
SELECT u.email                                   AS quem_perguntou,
       c.id                                      AS conversa,
       c.title                                   AS titulo_da_conversa,
       p.created_at AT TIME ZONE 'America/Sao_Paulo' AS perguntado_em,
       p.content                                 AS pergunta,
       r.content                                 AS resposta,
       ar.decision                               AS decisao,
       q.reference_query_id                      AS referencia,
       q.sql                                     AS sql_executado,
       ar.cost_estimate                          AS custo_usd
FROM jarvis.messaging_message p
JOIN jarvis.conversations_conversation c ON c.id = p.conversation_id
JOIN jarvis.auth_user u                  ON u.id = c.user_id
LEFT JOIN jarvis.messaging_message r     ON r.in_reply_to_id = p.id
LEFT JOIN jarvis.ai_orchestrator_aireply ar ON ar.message_id = p.id
LEFT JOIN LATERAL (
    SELECT reference_query_id, sql
    FROM jarvis.datasource_queryrun
    WHERE ai_reply_id = ar.id AND status = 'success'
    ORDER BY attempt DESC
    LIMIT 1
) q ON true
WHERE p.direction = 'in'
ORDER BY p.created_at DESC;
```

### Uso e custo por pessoa, por mês

```sql
SELECT u.email,
       date_trunc('month', ar.created_at AT TIME ZONE 'America/Sao_Paulo') AS mes,
       count(*)                                    AS perguntas,
       count(*) FILTER (WHERE ar.decision = 'answered') AS com_dado,
       round(sum(ar.cost_estimate), 4)             AS custo_usd
FROM jarvis.ai_orchestrator_aireply ar
JOIN jarvis.messaging_message p          ON p.id = ar.message_id
JOIN jarvis.conversations_conversation c ON c.id = p.conversation_id
JOIN jarvis.auth_user u                  ON u.id = c.user_id
GROUP BY 1, 2
ORDER BY 2 DESC, 5 DESC;
```

### O que o Jarvis ainda não sabe responder

```sql
SELECT g.created_at AT TIME ZONE 'America/Sao_Paulo' AS quando,
       u.email, g.question, g.reason
FROM jarvis.ai_orchestrator_cataloggap g
JOIN jarvis.messaging_message p          ON p.id = g.message_id
JOIN jarvis.conversations_conversation c ON c.id = p.conversation_id
JOIN jarvis.auth_user u                  ON u.id = c.user_id
WHERE g.status = 'open'
ORDER BY g.created_at DESC;
```

### Quem tentou entrar

```sql
SELECT email,
       criado_em AT TIME ZONE 'America/Sao_Paulo' AS pedido_em,
       CASE WHEN usado_em   IS NOT NULL THEN 'entrou'
            WHEN anulado_em IS NOT NULL THEN 'anulado'
            WHEN expira_em < now()      THEN 'expirou sem uso'
            ELSE 'pendente' END            AS resultado,
       tentativas, ip
FROM jarvis.web_codigodeacesso
ORDER BY criado_em DESC;
```

---

## Para treinar a IA no futuro

Tudo o que é preciso já está gravado. O que vale saber antes de montar uma
base de treino:

**Os pares pergunta → SQL são o material mais valioso.** A consulta "Cada
pergunta, quem fez…" já os entrega. Para ficar só com os bons exemplos:

- `decision = 'answered'`;
- SQL aprovado de primeira: `datasource_queryrun.attempt = 1` e
  `status = 'success'`;
- sem reescrita por ancoragem: `NOT (ar.raw_response ? 'rascunho_reprovado')`.

**Os erros também ensinam.** Quando há duas tentativas em `queryrun`, a
primeira com `error` e a segunda com `success`, o par mostra o erro que a IA
comete e como corrigir. `rascunho_reprovado` mostra o texto que citou número
inexistente — um exemplo negativo pronto.

**A versão importa.** `prompt_version` e `catalog_hash` dizem com que prompt
e com que documento de referência cada resposta foi dada. Resposta antiga
pode estar certa para as regras da época e errada para as de hoje; filtre
pela versão atual ou trate as antigas à parte.

**Cuidados com o conteúdo:**

- `result_sample` carrega **dado de negócio real**, até 500 linhas por
  consulta. Para ensinar a escrever SQL, ele não é necessário — e é o campo
  mais sensível do schema.
- Perguntas e respostas citam **nomes de pessoas** (representantes, médicos).
  Uso interno, para melhorar o próprio Jarvis, é uma coisa; mandar isso para
  treinar um modelo de terceiro é outra, e precisa passar pelo responsável
  pela LGPD na Ease.
- Conversas "excluídas" pelo usuário (`deleted_at` preenchido) continuam
  aqui. Se a regra for respeitar a vontade de quem excluiu, filtre
  `c.deleted_at IS NULL`.

---

## Onde isso é definido

| Tabela | Modelo |
|---|---|
| `conversations_*` | `app/conversations/models.py` |
| `messaging_message` | `app/messaging/models.py` |
| `ai_orchestrator_*` | `app/ai_orchestrator/models.py` |
| `datasource_*` | `app/datasource/models.py` |
| `web_codigodeacesso` | `app/web/models.py` |

A estrutura muda só por migração do Django (`manage.py migrate`), rodada
como `jarvis_app`. Se este documento e o banco divergirem, vale o banco — e
este documento precisa ser atualizado.
