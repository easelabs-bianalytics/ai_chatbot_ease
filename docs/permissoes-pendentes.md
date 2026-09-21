# Permissões que faltam para concluir o projeto

Estado em 2026-09-18, revisado depois de conferir o Terraform vivo do cockpit
(`sales_force_crm/infra/`). Serve de registro do que foi pedido a
quem, e do que ainda depende de terceiros. Pendente hoje: **um `GRANT` no banco** (seção 1). O
resto são decisões e configuração.

Duas decisões que encurtam muito a lista:

- **O projeto não depende de nenhum schema de outro sistema.** Nada é pedido no
  `trade_fv`, no `eventos` ou em qualquer outro. A lista de usuários entra por
  arquivo e a manutenção é pelo Admin do Django.
- **O Jarvis é mais um schema no `easelabs`**, não um banco novo — o mesmo
  padrão de `cockpit`, `trade_fv`, `app_pipelines` e `app_api`.

---

## 1. Banco de dados — falta um GRANT

O Jarvis grava usuários, histórico de conversas e auditoria num **schema
`jarvis` dentro do database `easelabs`**, na instância `cockpit-prod-db`.

| O que | Estado |
|---|---|
| `CREATEROLE` (criar `jarvis_app` e `jarvis_ro`) | ✅ concedido em 2026-09-18 |
| `CREATEDB` | ✅ concedido junto, mas **não é usado** — ficou da versão antiga do pedido, quando a ideia era um database separado |
| **`CREATE` no database `easelabs`** (criar o schema) | 🔲 **falta** — conferido no banco em 2026-09-18 |
| Qualquer privilégio sobre dado de negócio | não foi pedido — segue o que o `bi_chatbot_ro` já tem |

**O que falta, e por que não é o mesmo que já veio.** `CREATEDB` e `CREATEROLE`
são atributos de cluster: permitem criar *databases* e *roles*. Criar um schema
dentro de um database de outro dono é um privilégio do próprio database, e a
ACL do `easelabs` hoje dá `C` só a `cockpit_admin` e `app_pipelines` — o
`rubens_dba` não aparece nela. Conferido pelo túnel:
`has_database_privilege('rubens_dba','easelabs','CREATE')` devolve `f`.

Dois caminhos, qualquer um destrava — quem executa é quem tem o `cockpit_admin`:

```sql
-- A) uma linha, e o resto sai daqui
GRANT CREATE ON DATABASE easelabs TO rubens_dba;

-- B) ou a DBA roda ela mesma o script pronto, passando as duas senhas:
--    infra/app-db/02_criar_schema_jarvis.sql
```

**B é mais parecido com o que já existe na instância**: os schemas `cockpit` e
`trade_fv` pertencem ao `cockpit_admin` e foram criados por ela. Se preferir
manter a posse assim, em vez de `AUTHORIZATION jarvis_app`, basta somar
`GRANT CREATE, USAGE ON SCHEMA jarvis TO jarvis_app`.

Continua sem pedido de `SUPERUSER` e de `rds_superuser`.

### Com isso, o que eu faço em seguida (sem novo pedido)

1. [`infra/app-db/02_criar_schema_jarvis.sql`](../infra/app-db/02_criar_schema_jarvis.sql)
   — cria a role `jarvis_app` e o schema `jarvis`, com `search_path` fixo na
   role. Não cria database, não toca em schema existente, não cria tabela.
   **Executado em 2026-09-21**, junto com o `migrate`.
2. `manage.py migrate` — cria as 18 tabelas dentro do schema `jarvis`. Não há
   DDL para ninguém revisar: o Django gera e aplica tudo num comando. Dez
   dessas tabelas são do próprio framework (login, sessão, permissões,
   controle de versão do schema) e ocupam algumas dezenas de kB; as outras
   oito são as do produto. O banco inteiro, com 47 perguntas já respondidas,
   ocupa 1,4 MB hoje.
3. `manage.py sincronizar_usuarios --arquivo infra/app-db/usuarios_iniciais.csv`
   — cria os administradores, sem senha utilizável; cada um define a sua.

### Por que schema e não database separado

A versão anterior deste documento recomendava `CREATE DATABASE jarvis` e dizia
que colocar as tabelas no `easelabs` enfraqueceria a garantia de somente
leitura. Isso estava errado: a garantia de leitura é de outra conexão, com
outra role (`bi_chatbot_ro`, `default_transaction_read_only`, mais o
`sql_guard`) — ADR-0008, não ADR-0002. O que o database separado protegia eram
duas coisas, e as duas ficam mais firmes com privilégio de banco:

| Risco | Como fica |
|---|---|
| `migrate` criar tabela do Django em schema de negócio | `search_path = jarvis` fixado na role e `jarvis_app` sem `CREATE` em nenhum outro schema |
| a suíte de testes criar e apagar `test_*` em produção | `jarvis_app` sem `CREATEDB`, e `settings_test.py` recusando host de RDS |

O passo a passo de execução está em [`docs/plan.md`](plan.md), Fase 9,
passo 1.

---

## 2. AWS — nada a pedir, desde que o nome siga a convenção

Conferido no Terraform em 2026-09-18: o usuário IAM `rubens` **já tem as
permissões de deploy** (`infra/iam_deploy_rubens.tf` do `sales_force_crm`) —
ECR, ECS, ELB, ACM, security groups, Secrets Manager, CloudWatch e o state do
Terraform em S3 com lock no DynamoDB.

Elas são escopadas **por convenção de nome**, não por lista de aplicações, com
a intenção declarada de cobrir app novo sem editar a policy. Daí a única regra
que precisa ser respeitada:

> Todo recurso do Jarvis se chama `cockpit-prod-jarvis-*`. Fora dessa
> convenção, o `apply` falha por permissão.

Também não é mais necessário pedir:

- **ElastiCache** — não há Redis em produção e o Jarvis não vai criar um: a
  fila do Celery roda como container na própria task (ver Fase 9).
- **Bucket de estado do Terraform** — já existe
  (`cockpit-prod-terraform-state-595324409476`).
- **VPC, ALB, cluster ECS, log group, execution role** — todos já de pé e
  compartilhados.

O que resta, e é decisão e não permissão:

- [ ] regra nova no **security group do RDS** aceitando o SG do Jarvis na 5432
      com SSL — entra pelo Terraform, no mesmo `apply`;
- [ ] o ALB do cockpit é **público**. Se a ferramenta precisar ficar restrita à
      rede corporativa, isso não é "ALB interno" (seria outro ALB): é regra de
      listener por IP de origem ou autenticação no próprio app — **decidir**.

---

## 3. OpenAI — não é permissão, é configuração

Já está com você e não depende de ninguém:

- [ ] créditos pré-pagos com **recarga automática desligada** (é o que garante
      que nada seja cobrado do cartão além do crédito comprado);
- [ ] limite mensal ajustado ao volume e `AI_MONTHLY_BUDGET_USD` um pouco
      abaixo dele.

---

## 4. O que foi descartado, para não voltar à pauta

- **`GRANT SELECT` em `trade_fv.usuario`** — seria para sincronizar usuários
  automaticamente com o cadastro do Trade FV. Por decisão de 2026-09-18 o
  Jarvis não depende de schema de outro sistema: a lista inicial entra por
  arquivo e a manutenção é pelo Admin do Django. O comando
  `sincronizar_usuarios` mantém a opção `--do-banco` desligada, caso um dia
  se queira retomar.
- **Database `jarvis` separado, e instância RDS própria** — descartados em
  2026-09-18 pelo motivo da seção 1: fora do padrão da casa e sem ganho real
  de segurança.
