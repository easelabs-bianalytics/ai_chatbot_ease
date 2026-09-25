# Jarvis no WhatsApp: como funciona e como fazer o setup

O Jarvis responde também pelo WhatsApp, com as mesmas funções do chat web, que
continua como está. Este documento explica o uso e o passo a passo para ligar
o canal, do chip ao primeiro teste. As decisões e o porquê de cada uma estão
no [ADR-0028](adr/0028-canal-whatsapp-pela-evolution-api.md); o áudio, no
[ADR-0029](adr/0029-audio-no-whatsapp.md).

**Situação em 2026-09-25:** no ar, no privado e em grupos. O número
`553190054127` está conectado (passos 1 a 8 da seção 2). O Jarvis passa a
entender áudio (seção 1, "Áudio"); falta o teste com áudio de verdade depois
do deploy.

---

## 1. Como funciona para quem usa

### Conversa individual
- Só falam com o Jarvis os números **cadastrados no Admin**. Mensagem de
  qualquer outro número é ignorada em silêncio: o Jarvis não responde nem
  gasta nada.
- O cadastro pode ligar o número a um usuário do Jarvis: aí a conversa do
  WhatsApp aparece também na lista da pessoa no chat web (marcada
  **WhatsApp**), com o mesmo histórico e a mesma cota. Sem usuário, o Jarvis
  cria um usuário técnico para o número, sem login.
- A resposta vem **direto**, depois de uma espera sorteada de 3 a 30 segundos
  (seção 5), com "digitando…" enquanto o Jarvis consulta.
- Depois de **8 horas** sem mensagem, a próxima pergunta abre uma conversa
  nova, para o Jarvis não misturar o assunto de ontem com o de hoje.

### Grupos
- O Jarvis só responde em grupos **cadastrados no Admin**. Se alguém o
  colocar num grupo sem cadastro, ele fica calado.
- No grupo liberado, **qualquer membro** chama o Jarvis:
  - **marcando-o**: `@Jarvis quanto vendemos em agosto?`;
  - **respondendo a uma mensagem dele** (citação): `e em julho?` — por texto
    ou por áudio;
  - **dizendo "Jarvis" num áudio**: "Jarvis, quanto vendemos em agosto?";
  - **mandando um arquivo** logo depois de chamá-lo (até 5 minutos, a mesma
    pessoa): "Jarvis, preenche a planilha que vou mandar" + o arquivo.
- Mensagem **de texto** entre as pessoas do grupo **nunca** é lida pelo
  Jarvis. **Áudio** é diferente: para saber se disseram "Jarvis", todo áudio
  do grupo liberado é transcrito pela OpenAI, e o que não chama o Jarvis é
  descartado na hora, sem registro (ADR-0029).
- A resposta cita a pergunta de quem chamou.
- A cota é **do grupo** (30 por dia e 150 por semana por padrão, ajustável no
  cadastro).
- ⚠️ **Tudo o que o Jarvis responde num grupo fica visível para todos os
  membros.** Liberar um grupo é decidir que aquelas pessoas veem dado de
  negócio (O-18).

### Chat web × WhatsApp

| | Chat web | WhatsApp |
|---|---|---|
| Texto | Markdown formatado | o mesmo texto, com negrito e listas do WhatsApp |
| Gráfico | interativo (passar o mouse, legenda) | imagem PNG, com os mesmos dados e o mesmo polimento do servidor |
| Tabela | até 100 linhas na tela | até 12 linhas no texto; mais que isso vai como `.xlsx` |
| Planilha | botão "Baixar Excel" | arquivo `.xlsx`, quando a pessoa pede planilha ou a lista é longa |
| Planilha preenchida | download na tela | o arquivo volta na conversa |
| Enquanto pensa | "Entendi: …" e as etapas ao vivo | só "digitando…"; a resposta vem direto |
| Fonte e consulta | botão "Ver fonte" | comando `fonte` |
| 👎 | com o campo "o que estava errado" | reação 👎, sem comentário (escrever a crítica na mensagem seguinte faz o Jarvis refazer) |
| Continuações | botões | lista numerada: responda 1, 2 ou 3 |
| Áudio | ditado pelo microfone | transcrito; a resposta começa com "🎙️ Ouvi: …" (no grupo, só se citar o Jarvis ou disser "Jarvis") |

### Áudio

O Jarvis **ouve áudio** (ADR-0029, 2026-09-25). O áudio é transcrito e vira a
pergunta, exatamente como se tivesse sido escrita: mesmas regras, mesma cota,
mesma consulta ao banco.

**Quem ele atende:**

| Onde | Áudio atendido | Áudio ignorado |
|---|---|---|
| Privado (contato liberado) | todos | — |
| Grupo liberado | o que **responde (cita) uma mensagem do Jarvis**, mesmo sem dizer o nome; o que **diz "Jarvis"** ("Jarvis, quanto vendemos em agosto?") | todos os outros: descartados na hora, sem gravar nem responder |
| Número ou grupo não liberado | — | todos, sem baixar nem transcrever |

**O que volta:** a resposta começa dizendo o que ele ouviu, para a pessoa
perceber na hora um áudio mal entendido:

> 🎙️ _Ouvi:_ "Jarvis, quanto vendemos em agosto?"
>
> Foram 777 unidades em ago/2026…

A pergunta gravada é a transcrição: ela aparece assim no chat web e no Admin.

**Pedir a planilha antes de mandar:** "Jarvis, vou te mandar uma planilha,
preenche com o sell out de agosto" (por áudio ou texto) e, em seguida, o
arquivo sem legenda. O arquivo continua o pedido anterior da conversa. No
grupo, ele conta como chamada mesmo sem marcação, se vier da mesma pessoa até
5 minutos depois de ela chamar o Jarvis. Arquivo sem legenda e sem pedido
antes: o Jarvis descreve o que viu e oferece preencher.

**Limites:**
- Áudio acima de **3 minutos** não é transcrito: no privado (ou citando o
  Jarvis no grupo) ele avisa e pede um áudio mais curto ou por escrito.
- Áudio que não vira texto (ruído, silêncio, falha do serviço): "Não consegui
  entender o áudio. Pode repetir ou mandar por escrito?".
- **"Parar" só por texto:** o áudio espera a transcrição, e o "parar" precisa
  agir na hora.
- Nomes difíceis podem sair trocados na transcrição; o "Ouvi" existe para
  isso. Termos da casa (PX, sell out, as redes, os representantes mais
  comuns) vão como vocabulário para o modelo acertar.

**Privacidade no grupo:** para saber se disseram "Jarvis", **todo áudio do
grupo liberado passa pela OpenAI**. O que não chama o Jarvis é descartado na
hora: nem a mensagem nem o texto ficam gravados ou no log. Mensagem de texto
entre as pessoas continua nunca sendo lida. Liberar um grupo inclui isso
(O-18).

**Custo:** a transcrição é cobrada por minuto de áudio (~US$ 0,003 no
`gpt-4o-mini-transcribe`), não por token, e procurar o nome é uma busca no
texto, sem chamar a IA. Um grupo com 20 áudios de 30 s por dia custa ~US$ 0,90
por mês; um muito ativo (100 áudios de 1 min por dia), ~US$ 9. A resposta em
si custa o mesmo que a de uma pergunta escrita.

**Configuração:** nenhuma infra nova. Usa a mesma chave da IA
(`AI_PROVIDER_API_KEY`); o modelo pode ser trocado por
`WHATSAPP_MODELO_TRANSCRICAO` (vazio = `gpt-4o-mini-transcribe`).

**No log** (`jarvis-worker`): `WhatsApp: áudio de 12s transcrito (~US$
0.0006)` e o resultado do evento — `respondida`, `audio_sem_jarvis`,
`audio_longo`, `audio_nao_entendido`.

### Comandos

| Mande | O que acontece |
|---|---|
| `parar` | Interrompe a resposta em andamento |
| `nova conversa` | Começa um assunto novo |
| `fonte` | Mostra a consulta que sustentou a última resposta |
| `1`, `2` ou `3` | Escolhe uma das continuações sugeridas |

Nos grupos, os comandos também precisam marcar o Jarvis (`@Jarvis parar`).

### Anexos, áudio e avaliação
- **Planilha** (`.xlsx`, `.csv`) ou **imagem** enviadas ao Jarvis passam pela
  mesma validação do chat web. A legenda vira a pergunta ("preencha as
  unidades de agosto").
- **Áudio** é transcrito e vira a pergunta (ADR-0029). A resposta começa com
  `🎙️ Ouvi: "…"`, para conferir se ele entendeu. No privado, todo áudio é
  atendido; no grupo, o que cita uma mensagem do Jarvis ou diz "Jarvis".
  Áudio acima de 3 minutos não é transcrito. "Parar" continua por texto.
- **Arquivo depois do pedido:** "preenche a planilha que vou te mandar" (por
  texto ou áudio) e, em seguida, o arquivo sem legenda: o Jarvis faz o que foi
  pedido. Arquivo sem legenda e sem pedido antes: ele descreve o que viu e
  oferece preencher.
- **👍 ou 👎** como reação numa mensagem do Jarvis vira avaliação da resposta.
  O 👎 entra na fila de casos de teste (`casos_do_uso`), como no chat web.
  Tirar a reação desfaz a avaliação.

---

## 2. Setup em produção

A infra está no Terraform do `sales_force_crm`, branch `feat/infra-jarvis`,
e segue as regras de lá:
- `plan` antes de todo `apply`, lendo o diff;
- `.tf` commitado e empurrado antes do `apply`;
- `apply` sempre com `-target`;
- nunca cortar a saída do `apply`.

Os passos 1 a 6 podem ser feitos **antes do chip chegar**: o canal fica no ar
sem número, sem fazer nada.

### Passo 1: banco da Evolution (D-07)
A Evolution guarda a sessão do número no schema `evolution` do `easelabs`,
com uma role própria. Mensagens e contatos não são gravados por ela.

```bash
aws rds create-db-snapshot --region sa-east-1 \
  --db-instance-identifier cockpit-prod-db \
  --db-snapshot-identifier cockpit-prod-db-antes-jarvis-evolution-AAAAMMDD
aws rds wait db-snapshot-available --region sa-east-1 \
  --db-snapshot-identifier cockpit-prod-db-antes-jarvis-evolution-AAAAMMDD
```

Depois, rode `infra/rds/04_criar_schema_evolution.sql` com o master, pelo
túnel. A senha entra como variável do psql (`-v senha_evolution=...`),
gerada na hora (`openssl rand -hex 24`), e vai direto para o secret
`cockpit-prod-jarvis-evolution-db-uri` do passo 2. A última consulta do
script confere o resultado.

**✅ Feito em 2026-09-24.** Snapshot
`cockpit-prod-db-antes-jarvis-evolution-20260924`; o secret
`cockpit-prod-jarvis-evolution-db-uri` foi criado junto, com a senha gerada
no mesmo comando (nunca impressa). O script precisou da mesma linha do schema
`jarvis` (Fase 9, passo 1): `GRANT jarvis_evolution TO CURRENT_USER WITH SET
TRUE, INHERIT FALSE`, sem a qual o `CREATE SCHEMA ... AUTHORIZATION` para em
`must be able to SET ROLE`. Os avisos do `GRANT CONNECT` e do `REVOKE CREATE
ON SCHEMA public` são esperados: o `CONNECT` já vem do `PUBLIC`, e o `public`
já não aceita `CREATE` de ninguém.

Prova, conectando como `jarvis_evolution` com a senha do secret:

| Tentativa | O banco respondeu |
|---|---|
| `search_path` | `evolution` |
| `CREATE TABLE` no `evolution` | funcionou |
| `CREATE TABLE public.…` | `permission denied for schema public` |
| `SELECT … FROM cddd.fato_cdd` | `permission denied for schema cddd` |
| `SELECT … FROM jarvis.messaging_message` | `permission denied for schema jarvis` |

### Passo 2: três secrets
São criados à mão, como os outros do Jarvis. Rode no WSL (bash):

```bash
aws secretsmanager create-secret --region sa-east-1 \
  --name cockpit-prod-jarvis-evolution-api-key \
  --secret-string "$(openssl rand -hex 32)"

aws secretsmanager create-secret --region sa-east-1 \
  --name cockpit-prod-jarvis-whatsapp-webhook-token \
  --secret-string "$(openssl rand -hex 32)"

# ✅ já criado no passo 1 (2026-09-24), junto com a senha
aws secretsmanager create-secret --region sa-east-1 \
  --name cockpit-prod-jarvis-evolution-db-uri \
  --secret-string 'postgresql://jarvis_evolution:<senha-do-passo-1>@<host-do-rds>:5432/easelabs?schema=evolution&sslmode=require'
```

**✅ Os três existem desde 2026-09-24** (o `db-uri` saiu no passo 1). Valores
gerados no próprio comando, nunca impressos.

⚠️ Os secrets precisam existir **antes** do passo 6. A task nova do Jarvis
pede dois deles e, sem eles, fica presa em `ResourceInitializationError`.

### Passo 3: repositório da imagem da Evolution
Commit e push dos `.tf` na `feat/infra-jarvis`. Depois:

```bash
terraform plan -target=aws_ecr_repository.jarvis_evolution \
               -target=aws_ecr_lifecycle_policy.jarvis_evolution
terraform apply -target=aws_ecr_repository.jarvis_evolution \
                -target=aws_ecr_lifecycle_policy.jarvis_evolution
```

**✅ Feito em 2026-09-24.** `.tf` do WhatsApp commitados na
`feat/infra-jarvis` (`0b975cb`, depois de trazer a `main`); `plan` com alvo:
2 a criar, 0 a mudar, 0 a destruir; `apply` igual.

### Passo 4: espelhar a imagem
A imagem vai para o ECR porque o Docker Hub tem limite de download por IP,
que derruba o start da task. A versão é fixa (v2.3.7, a validada).

```bash
aws ecr get-login-password --region sa-east-1 | docker login --username AWS \
  --password-stdin 595324409476.dkr.ecr.sa-east-1.amazonaws.com
docker pull --platform linux/amd64 evoapicloud/evolution-api:v2.3.7
docker tag evoapicloud/evolution-api:v2.3.7 \
  595324409476.dkr.ecr.sa-east-1.amazonaws.com/cockpit-prod-jarvis-evolution:v2.3.7
docker push 595324409476.dkr.ecr.sa-east-1.amazonaws.com/cockpit-prod-jarvis-evolution:v2.3.7
```

**✅ Feito em 2026-09-24.** `cockpit-prod-jarvis-evolution:v2.3.7` no ECR,
`linux/amd64`, 388 MB. O aviso do `push` ("Not all multiplatform-content is
present") é esperado: só a plataforma do Fargate foi baixada.

### Passo 5: imagem do Jarvis e migrações
É o deploy de sempre (Fase 9, passos 8 a 10):
1. Construa e empurre a imagem com este código.
2. Rode a task avulsa de `migrate`, com snapshot antes. As migrações novas
   são `conversations.0004`, `messaging.0007` e `whatsapp.0001`.
3. Faça o bump de `jarvis_container_image`.

### Passo 6: `plan` e `apply` com alvo
```bash
terraform plan \
  -target=module.network.aws_security_group.jarvis_evolution \
  -target=module.network.aws_security_group.rds \
  -target=module.network.aws_service_discovery_private_dns_namespace.jarvis \
  -target=module.compute.aws_service_discovery_service.jarvis_evolution \
  -target=module.compute.aws_ecs_task_definition.jarvis_evolution \
  -target=module.compute.aws_ecs_service.jarvis_evolution \
  -target=module.compute.aws_iam_role_policy.execution_jarvis_evolution_secrets \
  -target=module.compute.aws_ecs_task_definition.jarvis \
  -target=module.compute.aws_ecs_service.jarvis \
  -target=module.compute.aws_iam_role_policy.execution_jarvis_secrets
```

**O que conferir no diff:**
- `aws_security_group.rds` tem de sair *update in-place*, nunca *replace*;
- a task do Jarvis sobe de 1024 para 2048 MB;
- nada fora da lista.

Com o diff certo, rode o `apply` com os mesmos `-target`.

**✅ Passos 5 e 6 feitos em 2026-09-24.** A parte do Jarvis subiu antes, no
deploy da `77a9fa4` (task com 2 GB, secrets e variáveis do WhatsApp, DNS
interno); as migrações já tinham rodado no da `89ee6b0`. O `apply` do passo 6
deu `5 added, 2 changed, 0 destroyed`: o `rds-sg` só ganhou a regra da
Evolution (in-place) e a permissão do Jarvis, os dois secrets novos. A
Evolution subiu com 1 task e conectou no banco (`Repository:Prisma - ON`).

Depois, confira:
- **No ECS:** `cockpit-prod-jarvis-evolution-service` com 1 task rodando.
- **No Admin do Jarvis** → **Conexão do WhatsApp**: o estado deve aparecer.
  Se aparecer "A Evolution não respondeu", veja o log `jarvis-evolution` no
  CloudWatch.

### Passo 7: conectar o número (com o chip)
1. Admin → **Conexão do WhatsApp** → **Configurar a instância**. Isso cria a
   instância, liga os grupos (a trava é o cadastro), recusa chamadas e aponta
   o webhook.
2. Clique em **Mostrar o QR para parear**.
3. No celular do Jarvis: WhatsApp → **Aparelhos conectados** → **Conectar
   aparelho**, e leia o QR. Ele vale por poucos segundos; se expirar,
   recarregue a página.
4. O estado muda para **open — conectado**, e "Conectado como" mostra o
   número.

Pelo terminal (ECS Exec), o equivalente é
`python app/manage.py whatsapp_configurar --qr`.

**✅ Feito em 2026-09-24.** Estado `open`, conectado como
`553190054127@s.whatsapp.net` (perfil "Jarvis 2.0"). Conferido de dentro da
task do Jarvis: webhook ligado, só `MESSAGES_UPSERT`, apontando para
`https://jarvis.easelabs.app.br/api/whatsapp/webhook/<segredo>/`; chamadas
recusadas, grupos ligados, nada marcado como lido, sem histórico.

⚠️ **O WhatsApp registrou o número sem o nono dígito** (`55 31 9005-4127`, e
não `55 31 99005-4127`). É comum em celulares do Brasil. Desde a `83f2df5`
o Jarvis compara os celulares com e sem o 9, nos contatos e na marcação.

### Passo 8: número do Jarvis na configuração
Preencha no Terraform, faça `plan` e `apply` da task do Jarvis e commite
(`deploy: ...`):
- `jarvis_whatsapp_numero`: o número de "Conectado como", só dígitos
  (`5511...`). É o que faz a marcação `@Jarvis` funcionar nos grupos.
- `jarvis_whatsapp_lid`: deixe vazio. O Jarvis aprende o próprio @lid
  sozinho (passo 9).

**✅ Feito em 2026-09-24.** `jarvis_whatsapp_numero = "553190054127"`,
exatamente como o WhatsApp o identifica (commit `50aa7ce` na
`feat/infra-jarvis`), junto com a imagem `83f2df5`. `plan` só com a imagem e
a variável; `apply` `1 added, 1 changed, 1 destroyed`.

### Passo 9: cadastros e testes
1. **Contato de teste:** Admin → **Contatos do WhatsApp** → adicionar. O
   número vai com DDI e DDD (`5511999998888`), com ou sem o nono dígito
   (o Jarvis aceita as duas formas). Só o número basta: o @ do WhatsApp não
   é usado. **Usuário é opcional:** com ele, a conversa aparece no chat web
   da pessoa; vazio, o Jarvis cria um usuário técnico para o número
   (`whatsapp-<número>`, sem login), com o nome do cadastro.
2. **Teste individual**, na ordem:
   - uma pergunta com número;
   - um pedido de gráfico;
   - "em Excel";
   - uma reação 👎;
   - `fonte`;
   - `parar` durante uma resposta longa.
3. **Grupo de teste**, só com o time. Adicione o número do Jarvis ao grupo.
   Na página **Conexão do WhatsApp** aparece a lista **Grupos de que o Jarvis
   participa**, com o identificador (`...@g.us`). Cadastre-o em **Grupos do
   WhatsApp**.
4. **Teste no grupo:**
   - uma mensagem sem marcar o Jarvis: ele fica calado;
   - `@Jarvis vendas de agosto`: ele responde citando a pergunta;
   - uma resposta citando a mensagem dele: ele responde.
5. **Teste de áudio:**
   - no privado, um áudio com uma pergunta: a resposta começa com
     "🎙️ Ouvi: …";
   - no grupo, um áudio **sem** dizer "Jarvis": ele fica calado;
   - no grupo, "Jarvis, quanto vendemos em agosto?": ele responde citando;
   - no grupo, um áudio respondendo (citando) uma mensagem dele: ele
     responde, mesmo sem dizer o nome;
   - "Jarvis, vou te mandar uma planilha, preenche com o sell out de agosto" e,
     logo depois, a planilha sem legenda: ele preenche.
6. **Grupo que esconde os números (@lid):** a marcação chega com o
   identificador escondido (`...@lid`), e não com o número. Desde
   2026-09-24 o Jarvis **aprende o próprio @lid sozinho**: na primeira
   marcação por @lid num grupo liberado, ele lê a lista de participantes, que
   liga cada @lid ao número, e guarda o dele. Não é preciso configurar
   `jarvis_whatsapp_lid` (ele continua valendo, se preenchido). Escrever
   `@jarvis` à mão funciona sempre.

---

## 3. Operação do dia a dia

### A visão de admin

**Quem tem:** só o Rubens (`rubens.filho@easelabs.com.br`) e o Paulo
(`paulo.lima@easelabs.com.br`), decidido pelo Rubens em 2026-09-24. Os dois
são `is_staff` e `is_superuser` no `auth_user` de produção; os demais
usuários, inclusive os que vieram como admin no `usuarios_iniciais.csv`,
tiveram o acesso retirado.

⚠️ O `sincronizar_usuarios` marca como `is_staff` todo mundo que vem com
papel `admin` na origem. Rodado de novo, ele devolveria o acesso à Natália e
ao Fernando: depois dele, repita a retirada (tarefa avulsa com
`manage.py shell`, deixando `is_staff`/`is_superuser` só nos dois e-mails).

**Como entrar:**
1. Abra https://jarvis.easelabs.app.br/admin/.
2. O Admin manda para o login por código: digite o e-mail e o código que
   chega nele. Depois do código, o Admin abre.

**Conectar o WhatsApp** (com o chip no celular do Jarvis):
1. Admin → **Conexão do WhatsApp**
   (https://jarvis.easelabs.app.br/admin/whatsapp/conexao/).
2. **Configurar a instância**, uma vez: cria a instância `jarvis` na
   Evolution, liga os grupos, recusa chamadas e aponta o webhook para o
   Jarvis. Pode ser repetido sem estragar nada.
3. **Mostrar o QR para parear**. No celular: WhatsApp → **Aparelhos
   conectados** → **Conectar aparelho**, e leia o QR. Ele expira em poucos
   segundos; se expirar, recarregue a página.
4. O estado muda para **open — conectado**, com o número em "Conectado como".
   Siga para o passo 8 da seção 2.

**O que a página de conexão mostra e faz:**

| Parte | Para quê |
|---|---|
| Estado da conexão | `open` = conectado; outro estado = precisa do QR. "A Evolution não respondeu" = o service da Evolution está fora (log `jarvis-evolution`) |
| Configurar a instância | cria ou reconfigura a instância e o webhook |
| Mostrar o QR para parear | o QR para ligar o número ao Jarvis |
| Grupos de que o Jarvis participa | nome e identificador (`...@g.us`) de cada grupo, para copiar no cadastro |
| Menções que o Jarvis não reconheceu | marcações de outras pessoas em grupos liberados; o @lid do Jarvis ele aprende sozinho |

**O que o Admin tem além da página de conexão:**

| Tela | O que se faz nela |
|---|---|
| Contatos do WhatsApp | liberar uma pessoa (número com DDI e DDD → usuário do Jarvis), desativar, anotar |
| Grupos do WhatsApp | liberar um grupo (identificador `...@g.us`), o usuário técnico dele e a cota diária e semanal |
| Envios do WhatsApp | o id de cada mensagem que o Jarvis mandou, para ligar reação e citação à resposta |
| Conversas e Mensagens | todas as conversas, do chat web e do WhatsApp; a mensagem que falhou aparece com o status e o detalhe |
| Avaliações de resposta | os 👍/👎 com o comentário, que viram casos de teste (`casos_do_uso`) |
| Usuários | ativar, desativar e dar ou tirar o acesso de admin |

No chat, quem é admin também vê o custo e os tokens de cada resposta, em
"Fonte".

### Situações comuns

| Situação | O que fazer |
|---|---|
| Liberar uma pessoa | Admin → Contatos do WhatsApp → adicionar (número + usuário) |
| Tirar uma pessoa | Desmarcar **ativo** no cadastro. Usuário desativado no Jarvis também para de falar |
| Liberar um grupo | Adicionar o Jarvis ao grupo, copiar o identificador na página de conexão e cadastrar em Grupos do WhatsApp |
| Ajustar a cota de um grupo | No cadastro do grupo: limite diário e semanal |
| Número desconectou (estado ≠ open) | Página de conexão → Mostrar o QR → ler no aparelho. A sessão volta sozinha quando a task reinicia; o QR só é preciso se o WhatsApp desvincular o aparelho |
| Número restringido pelo WhatsApp | Aviso no aparelho. Pare o uso por alguns dias; se persistir, troque de chip (passos 7 e 8) e revise o volume |
| Resposta não chegou no WhatsApp | A resposta fica gravada e visível no chat web. A mensagem sai com status "Falhou" no Admin (Mensagens), com o detalhe |
| Ver o que aconteceu com um evento | Log `jarvis-worker` no CloudWatch: `WhatsApp: evento respondida`, `contato_nao_liberado`, `grupo_sem_mencao`, `audio_sem_jarvis`… |
| Áudio mal entendido | O "🎙️ Ouvi" mostra o que ele entendeu: repetir o áudio mais devagar ou mandar por escrito. A transcrição fica na pergunta, no chat web e no Admin |
| Atualizar a versão da Evolution | Espelhar a versão nova (passo 4), mudar `jarvis_evolution_container_image`, `plan`/`apply`. O WhatsApp fica fora ~1 min e a sessão volta sem QR |

**Custo:**
- Evolution: ~US$ 10/mês (0,25 vCPU, 512 MB).
- Task do Jarvis de 2 GB: ~US$ 4/mês a mais.
- Perguntas: o mesmo custo de IA do chat web, dentro do mesmo teto mensal.
- Áudio: ~US$ 0,003 por minuto transcrito (seção 1, "Áudio").

---

## 4. Desenvolvimento local

```bash
docker compose exec db psql -U bi_chatbot -d bi_chatbot -c "CREATE SCHEMA IF NOT EXISTS evolution;"
docker compose --profile whatsapp up -d evolution        # http://localhost:8082 (Manager em /manager)
```

No `bi/.env` (nunca commitado):
- `EVOLUTION_API_BASE_URL=http://localhost:8082`
- `EVOLUTION_API_KEY=troque-esta-chave-local`
- `EVOLUTION_INSTANCE_NAME=jarvis_local`
- `WHATSAPP_WEBHOOK_TOKEN=<qualquer segredo>`
- `WHATSAPP_WEBHOOK_BASE_URL=http://host.docker.internal:8000`
- `WHATSAPP_WEBHOOK_SO_LOCAL=0`

Depois, com o servidor e o worker de sempre rodando:
`uv run python app/manage.py whatsapp_configurar`.

**Cuidados:**
- **Não pareie o chip de produção na máquina local.** Ele desconectaria a
  sessão de produção. Para testar de verdade, use outro número, fora de
  qualquer grupo.
- **Sem `EVOLUTION_API_KEY`** o canal usa o cliente de teste, e nada sai.
  Os testes automatizados (`uv run pytest`) nunca falam com a Evolution.

---

## 5. Limites e riscos

**Espera sorteada antes de responder (2026-09-24).** Toda mensagem espera
de 3 a 30 segundos, sorteados, antes de o Jarvis começar a atender (e antes
do "digitando"): resposta que sempre começa no mesmo instante
é padrão de robô. O `parar` continua imediato. Os limites são
`WHATSAPP_ATRASO_MIN_S` e `WHATSAPP_ATRASO_MAX_S` (padrão 3 e 30).

- **Protocolo não oficial:** a Evolution viola os termos do WhatsApp. O
  número pode ser restringido, e a sessão pode cair. O risco aqui é menor que
  na referência (poucos contatos, internos, sem tráfego pago), mas existe.
  Trocar para a API oficial da Meta no individual é escrever outro
  adaptador, sem mexer no resto (ADR-0005).
- **Dados em grupo:** a resposta é vista por todos os membros (O-18).
- **Uma sessão só:** o serviço da Evolution nunca roda duas cópias, porque o
  WhatsApp derrubaria as duas. Por isso ele é separado do Jarvis, e os
  deploys do Jarvis não tocam no WhatsApp.
- **Áudio (ADR-0029):** ~US$ 0,003 por minuto transcrito. Um grupo com 20
  áudios de 30 s por dia custa ~US$ 0,90 por mês; muito ativo (100 áudios de
  1 min por dia), ~US$ 9. Teto de 3 minutos por áudio.
- **Ainda não feito:** botões interativos (o WhatsApp
  não oferece botões para número comum; as continuações vão numeradas).

---

## 6. Onde está cada peça (inventário)

Tudo o que foi construído **só para o WhatsApp**, em 2026-09-23. Nada disso
foi commitado nem aplicado na AWS até o momento em que este inventário foi
escrito.

### 6.1 Infra na AWS (a criar; nomes finais)

| Recurso | Nome | Onde está declarado |
|---|---|---|
| Service ECS da Evolution | `cockpit-prod-jarvis-evolution-service` | `sales_force_crm/infra/modules/compute/jarvis_evolution.tf` |
| Task definition da Evolution | `cockpit-prod-jarvis-evolution` (0,25 vCPU, 512 MB) | idem |
| DNS interno (Cloud Map) | namespace `cockpit-prod-jarvis.local`, serviço `evolution` → `evolution.cockpit-prod-jarvis.local:8080` | namespace em `modules/network/main.tf`; serviço em `jarvis_evolution.tf` |
| Security group da Evolution | `cockpit-prod-jarvis-evolution-sg` (só o Jarvis na 8080) | `modules/network/main.tf` |
| Regra no RDS | ingresso 5432 vindo da Evolution, dentro de `cockpit-prod-rds-sg` | `modules/network/main.tf` |
| Repositório de imagem | ECR `cockpit-prod-jarvis-evolution` (tag `v2.3.7`) | `sales_force_crm/infra/ecr.tf` |
| Permissão de ler os secrets | `cockpit-prod-fargate-execution-jarvis-evolution-secrets` | `jarvis_evolution.tf` |
| Secrets (criados à mão) | `cockpit-prod-jarvis-evolution-api-key`, `cockpit-prod-jarvis-evolution-db-uri`, `cockpit-prod-jarvis-whatsapp-webhook-token` | Secrets Manager, sa-east-1 (passo 2) |
| Banco da Evolution (criado à mão) | role `jarvis_evolution`, schema `evolution` no `easelabs` | `bi/infra/rds/04_criar_schema_evolution.sql` |
| Task do Jarvis | 2 GB de memória e as variáveis `EVOLUTION_*` e `WHATSAPP_*` | `modules/compute/jarvis.tf` e `infra/variables.tf` |
| Logs | CloudWatch, prefixos `jarvis-evolution` (a Evolution) e `jarvis-worker` (o canal) | log group do cluster |

### 6.2 Arquivos no `sales_force_crm` (branch `feat/infra-jarvis`)

| Arquivo | O que tem |
|---|---|
| `infra/modules/compute/jarvis_evolution.tf` | **novo**: service, task, DNS interno e a permissão dos secrets da Evolution |
| `infra/modules/compute/jarvis.tf` | secrets e variáveis do WhatsApp no Jarvis |
| `infra/modules/compute/variables.tf` | variáveis da Evolution, do número e do @lid |
| `infra/modules/network/main.tf` | security group da Evolution, regra no RDS e namespace do DNS interno |
| `infra/modules/network/outputs.tf` | saídas do security group e do namespace |
| `infra/main.tf` | liga as saídas da rede ao módulo de compute |
| `infra/variables.tf` | imagem e tamanho da Evolution, número, @lid; Jarvis com 2 GB |
| `infra/ecr.tf` | repositório `cockpit-prod-jarvis-evolution` |

### 6.3 Arquivos no `bi/`: novos

| Arquivo | O que faz |
|---|---|
| `app/whatsapp/models.py` | cadastros `ContatoWhatsApp` e `GrupoWhatsApp`, e `EnvioWhatsApp` (id de cada mensagem enviada) |
| `app/whatsapp/entrada.py` | lê o evento da Evolution: texto, anexo, áudio, reação, menção, citação, @lid |
| `app/whatsapp/servicos.py` | o caminho inteiro: cadastro, menção, comandos, anexo, orquestrador, entrega |
| `app/whatsapp/saida.py` | monta a resposta para o WhatsApp (texto, tabela, imagem, planilha, continuações) |
| `app/whatsapp/formato.py` | Markdown → marcação do WhatsApp; tabela legível no celular; divisão em partes |
| `app/whatsapp/graficos.py` | gráfico em PNG com o `vl-convert` (Vega-Lite) |
| `app/whatsapp/cliente.py` | cliente da Evolution: o real (HTTP) e o fake (testes) |
| `app/whatsapp/aviso.py` | "digitando…" enquanto o Jarvis consulta (o "Entendi: …" saiu em 2026-09-24) |
| `app/whatsapp/audio.py` | transcrição do áudio (OpenAI e fake), "Jarvis" no áudio, custo (ADR-0029) |
| `app/whatsapp/config.py` | leitura das variáveis `EVOLUTION_*` e `WHATSAPP_*` |
| `app/whatsapp/views.py`, `urls.py` | webhook `/api/whatsapp/webhook/<segredo>/` e página de conexão do Admin |
| `app/whatsapp/templates/whatsapp/conexao.html` | a página de conexão (estado, QR, grupos, menções) |
| `app/whatsapp/admin.py`, `apps.py`, `tasks.py`, `__init__.py` | Admin dos cadastros, registro do app e tarefa Celery |
| `app/whatsapp/management/commands/whatsapp_configurar.py` | configura a instância pelo terminal |
| `app/whatsapp/migrations/0001_inicial.py` | tabelas do app |
| `app/messaging/channels/whatsapp/__init__.py` | o canal no contrato `Channel` (ADR-0005) |
| `app/messaging/fonte.py` | o que uma resposta mostra, extraído de `views.py` para os dois canais usarem |
| `app/messaging/planilha_da_resposta.py` | o `.xlsx` da resposta, extraído de `views.py` |
| `app/attachments/receber.py` | validação do anexo, extraída de `views.py` |
| `app/conversations/migrations/0004_canal_da_conversa.py` | campos `canal` e `whatsapp_jid` da conversa |
| `app/messaging/migrations/0007_autor_no_whatsapp.py` | quem perguntou, no grupo |
| `infra/rds/04_criar_schema_evolution.sql` | role e schema da Evolution |
| `docs/adr/0028-canal-whatsapp-pela-evolution-api.md` | a decisão |
| `docs/whatsapp.md` | este guia |
| `tests/integration/test_whatsapp.py` | caminho completo, com o cliente fake |
| `tests/unit/test_whatsapp_entrada.py` | leitura do evento, formato e gráfico |
| `tests/unit/test_whatsapp_cliente.py` | contrato HTTP com a Evolution |
| `tests/integration/test_whatsapp_audio.py` | áudio: privado, grupo com e sem "Jarvis", citação, arquivo depois do pedido |
| `docs/adr/0029-audio-no-whatsapp.md` | a decisão do áudio (custo e privacidade) |

### 6.4 Arquivos no `bi/`: alterados

| Arquivo | O que mudou |
|---|---|
| `app/config/settings.py`, `app/config/urls.py` | app `whatsapp` registrado; rotas do webhook e da página de conexão |
| `app/conversations/models.py` | `canal` e `whatsapp_jid` |
| `app/messaging/models.py` | `autor_externo` e `autor_nome` |
| `app/messaging/views.py` | usa as três extrações; a conversa diz o canal |
| `app/ai_orchestrator/progresso.py` | sinal `definido`, que o aviso do WhatsApp ouve |
| `app/ai_orchestrator/limites.py` | cota do grupo, pelo cadastro |
| `app/web/static/web/app.js`, `styles.css` | selo "WhatsApp" na lista de conversas |
| `pyproject.toml`, `uv.lock` | `vl-convert-python` e `requests` |
| `docker-compose.yml` | serviço `evolution` (perfil `whatsapp`, porta 8082) |
| `.env.example`, `.gitignore` | variáveis do WhatsApp; `whatsapp_qr.png` fora do git |
| `tests/conftest.py` | os testes nunca veem credencial da Evolution |
| `tests/integration/test_exportacao_excel.py` | segue a planilha para o módulo novo |
| `CLAUDE.md`, `docs/plan.md` (Fase 13 e pré-requisitos da Fase 9), `docs/open-decisions.md` (D-06, D-07, O-18) | documentação |

### 6.5 Na máquina local
- **Evolution local:** container `bi-evolution-1` (perfil `whatsapp`), parado.
- **Schema `evolution`** no Postgres de desenvolvimento (`bi_chatbot`).
