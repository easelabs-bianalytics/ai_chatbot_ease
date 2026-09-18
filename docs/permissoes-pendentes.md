# Permissões que faltam para concluir o projeto

Estado em 2026-09-18. O Jarvis roda inteiro na máquina local; o que falta
para ele subir na AWS são acessos, não código. Este documento lista cada um,
quem concede e o que exatamente precisa ser executado.

Uma decisão que encurta a lista: **o projeto não depende de nenhum schema de
outro sistema.** Nada é pedido no `trade_fv`, no `eventos` ou em qualquer
outro. O Jarvis tem o banco dele, com a tabela de usuários dele.

---

## 1. Banco de dados — pedido à DBA

**É o único item que bloqueia hoje.** O Jarvis precisa de um banco próprio
para usuários, histórico de conversas e auditoria.

O `rubens_dba` não consegue criá-lo: conferido em 2026-09-18, ele tem
`rolsuper = f`, `rolcreatedb = f`, `rolcreaterole = f` e nenhum `CREATE` no
database `easelabs`. Falta um comando, que a conta mestra da instância roda
uma vez:

```sql
ALTER ROLE rubens_dba CREATEDB CREATEROLE;
```

Script pronto, com a explicação para quem executa e a consulta de
conferência: [`infra/app-db/01_pedido_dba_permissoes.sql`](../infra/app-db/01_pedido_dba_permissoes.sql).

**O que isso libera, e só isso:**

| Atributo | Permite | Não permite |
|---|---|---|
| `CREATEDB` | criar databases novos | tocar em database existente, inclusive o `easelabs` |
| `CREATEROLE` | criar e administrar as roles que ele mesmo criar | mexer no `bi_chatbot_ro`, nas roles da DBA ou na conta mestra (PostgreSQL 16) |

Não há pedido de `SUPERUSER`, de `rds_superuser`, nem de privilégio novo
sobre dado de negócio. A leitura do chatbot continua sendo a que o
`bi_chatbot_ro` já tem nos seis schemas de sempre.

### Com essa permissão, o que eu faço em seguida (sem novo pedido)

1. `infra/app-db/02_criar_banco_jarvis.sql` — cria o database `jarvis`, as
   roles `jarvis_app` (escreve) e `jarvis_ro` (o time de BI lê a auditoria) e
   o schema `jarvis`. Já validado num PostgreSQL 16 local.
2. `manage.py migrate` — cria as 18 tabelas dentro do schema `jarvis`. Não há
   DDL para ninguém revisar: o Django gera e aplica tudo num comando. Dez
   dessas tabelas são do próprio framework (login, sessão, permissões,
   controle de versão do schema) e ocupam algumas dezenas de kB; as outras
   oito são as do produto. O banco inteiro, com 47 perguntas já respondidas,
   ocupa 1,4 MB hoje.
3. `manage.py sincronizar_usuarios --arquivo infra/app-db/usuarios_iniciais.csv`
   — cria os administradores, sem senha utilizável; cada um define a sua.

### Se a DBA recusar um database novo na instância

Plano B: uma instância RDS pequena só da aplicação (`db.t4g.micro`, ~US$ 15 a
25/mês). Os mesmos scripts valem, trocando o endpoint. O que **não** vamos
fazer é colocar as tabelas do Jarvis dentro do database `easelabs`: ali a
role que escreve passaria a se conectar no mesmo database dos dados de
negócio, e a garantia de somente leitura deixaria de ser estrutural.

---

## 2. AWS — pedido a quem administra a conta

Para o deploy com Terraform (Fase 9), o usuário/role que roda o `apply`
precisa poder criar e administrar:

| Serviço | Para quê |
|---|---|
| ECR | guardar a imagem da aplicação |
| ECS (Fargate) + IAM `CreateRole`/`PassRole` | os serviços `web` e `worker` e as roles de execução |
| Elastic Load Balancing + ACM | entrada HTTPS e certificado |
| ElastiCache | Redis da fila do Celery |
| Secrets Manager | chave da OpenAI, senhas do banco, `SECRET_KEY` |
| CloudWatch Logs | logs e alarmes |
| EC2 (grupos de segurança, subnets, VPC — leitura e escrita de SG) | ligar a aplicação ao RDS e ao Redis |
| RDS (`Describe*`) | descobrir endpoint e subnets da instância |
| S3 | bucket do estado do Terraform |

O caminho mais curto é a política gerenciada `PowerUserAccess` mais uma
política própria com `iam:CreateRole`, `iam:AttachRolePolicy` e `iam:PassRole`
restritas ao prefixo `jarvis-*`. Se a conta for gerida por SSO, basta um
perfil com esse conjunto.

Também é preciso, uma vez:

- [ ] autorizar a alteração do **security group do RDS** para aceitar conexão
      do security group da aplicação na 5432, com SSL;
- [ ] decidir se o ALB é **interno** (só rede corporativa/VPN — recomendado
      para ferramenta interna) ou público.

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
- **Schema do Jarvis dentro do `easelabs`** — descartado pelo motivo da
  seção 1.
