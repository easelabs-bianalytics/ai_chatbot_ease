# ADR-0028: Canal WhatsApp pela Evolution API, ao lado do chat web

## Status
Aceito — 2026-09-23.

## Contexto
O Rubens pediu que o Jarvis funcione também no WhatsApp, com as mesmas
funções do chat web e sem que o chat web mude:

- **Conversa individual:** só para os números que liberarmos.
- **Grupos:** o Jarvis responde quando alguém o marca com @jarvis.

O ADR-0007 tinha decidido "chat web, não WhatsApp" para o MVP. Este ADR
acrescenta o canal; não substitui o web.

A arquitetura já previa isso. Pelo ADR-0005, o orquestrador só conhece o
contrato `Channel`, e o projeto de referência (`avaliacao_eleitores`) tem um
adaptador da Evolution API em produção. Esse adaptador deixou duas lições
registradas:

- **Número restringido:** a linha foi restringida pelo WhatsApp duas vezes em
  três dias (ADR-0013 de lá). O motivo foi o volume de contatos novos vindos
  de tráfego pago.
- **Grupos:** um número conectado responde em todos os grupos de que já
  participa. A IA respondeu em dois grupos reais por engano (ADR-0007 de lá).

**Decisões do Rubens em 2026-09-23:**

- **Provedor:** Evolution API, com um chip novo usado só pelo Jarvis.
- **Grupos:** em grupo liberado, qualquer membro pode chamar o Jarvis.
- **Número:** será providenciado. Tudo é feito com testes sem rede antes, e
  conectar o número é o último passo.

A API oficial da Meta foi descartada por agora porque não entra em grupos já
existentes nem atende @menção como uma pessoa.

## Decisão

### Onde a Evolution roda
- **Serviço próprio no ECS** (`cockpit-prod-jarvis-evolution-service`), e não
  um container da task do Jarvis. O deploy do ECS sobe a task nova antes de
  derrubar a antiga. Com a Evolution dentro da task do Jarvis, todo bump de
  imagem deixaria duas sessões do mesmo número abertas ao mesmo tempo, e o
  WhatsApp derruba ou desconecta o aparelho nesse caso. Parar antes de subir
  tiraria o chat web do ar a cada deploy.
- **Nunca duas tasks:** o serviço da Evolution tem `desired_count = 1`,
  `maximum_percent = 100` e `minimum_healthy_percent = 0`. A versão é fixa
  (`evoapicloud/evolution-api:v2.3.7`, a validada na referência, espelhada no
  ECR), então esse serviço quase nunca é reimplantado. Os deploys do Jarvis
  não tocam na sessão.
- **Rede:**
  - o Jarvis chama a Evolution em
    `http://evolution.cockpit-prod-jarvis.local:8080`, pelo DNS privado da VPC
    (Cloud Map). O security group dela só aceita o Jarvis;
  - a Evolution devolve os eventos pelo webhook
    `https://jarvis.easelabs.app.br/api/whatsapp/webhook/<segredo>/`, pelo
    ALB. O segredo no caminho é a trava, porque a Evolution não manda
    cabeçalho próprio (como na referência);
  - a saída para o WhatsApp é pela subnet pública com IP público, como nos
    outros serviços.
- **Sem exposição pública da Evolution:** o QR de pareamento e o estado da
  conexão aparecem numa página do Admin do Jarvis (`/admin/whatsapp/conexao/`)
  e no comando `whatsapp_configurar`.
- **Banco:** a Evolution guarda só a sessão e a instância, no schema
  `evolution` do `easelabs`, com role própria (`jarvis_evolution`,
  `infra/rds/04_criar_schema_evolution.sql`). Mensagens, contatos e conversas
  não são gravados por ela (`DATABASE_SAVE_DATA_* = false`); o registro que
  vale é o do Jarvis. O cache é local, sem Redis.

### Quem fala com o Jarvis
- **Individual:** vale o cadastro `ContatoWhatsApp` (número → usuário do
  Jarvis). A conversa é desse usuário: aparece na lista dele no chat web, com
  o mesmo histórico, e usa a cota dele.
- **Grupo:** vale o cadastro `GrupoWhatsApp`, e qualquer membro pode chamar.
  - **Quando responde:** só quando alguém marca o número do Jarvis (@jarvis)
    ou responde a uma mensagem dele. Conversa entre as pessoas do grupo
    nunca é processada.
  - **Dono da conversa:** um usuário técnico por grupo, sem login. A cota é
    do grupo, com limites próprios no cadastro.
  - **Autoria:** o número e o nome de quem perguntou ficam gravados em cada
    mensagem.
- **Número ou grupo não liberado:** ignorado em silêncio, só com registro no
  log. Isso inclui grupos em que o número for colocado sem cadastro.
- **Configuração da instância:** `groupsIgnore` fica **desligado** (precisamos
  dos grupos), e a trava é o nosso cadastro. `rejectCall` fica ligado, e o
  Jarvis não marca nada como lido.

### Conversa
- **Histórico:** o WhatsApp é uma conversa sem fim; o Jarvis corta em
  conversas. Depois de 8 h sem mensagem, ou quando a pessoa escreve "nova
  conversa", a próxima mensagem abre outra. Assim o histórico que vai ao
  modelo continua sendo o do assunto atual.
- **Idempotência:** o id da mensagem no WhatsApp é o `client_message_id`. A
  Evolution reentrega o mesmo evento, e ele não vira duas perguntas.
- **Comandos:**
  - "parar": interrompe a resposta em andamento;
  - "nova conversa": abre outra conversa;
  - "fonte": manda a consulta da última resposta;
  - "1", "2" ou "3": escolhe uma das continuações sugeridas.

### Paridade com o chat web
A resposta é a mesma; o que muda é a forma de entregar:

| Chat web | WhatsApp |
|---|---|
| Markdown | Formatação do WhatsApp (`*negrito*`, listas); título vira negrito |
| Tabela na tela | Tabela curta em bloco monoespaçado; lista longa vai em `.xlsx` com resumo no texto |
| Gráfico (Chart.js ou Vega-Lite) | Imagem PNG, desenhada no servidor pelo `vl-convert` a partir da mesma especificação e dos dados do banco (ADR-0020, ADR-0026). O formato simples é convertido para Vega-Lite antes |
| Botão "Baixar Excel" | Arquivo `.xlsx` quando a pessoa pediu planilha ou a lista é longa |
| Planilha preenchida (ADR-0024) | Arquivo devolvido na conversa |
| Anexar planilha ou imagem | Documento `.xlsx`/`.csv` ou imagem enviados no WhatsApp, pelo mesmo caminho de validação e depósito |
| Continuações (botões) | Lista numerada ao fim da resposta |
| 👍/👎 (ADR-0027) | Reação 👍 ou 👎 na mensagem do Jarvis |
| "Entendi: …" enquanto pensa | "digitando…" e uma mensagem curta "Entendi: …" nas perguntas com consulta |
| Parar | "parar" |
| Fonte e consulta | "fonte" |

Áudio ainda não é transcrito: o Jarvis pede o texto.

## Consequências
- **Protocolo não oficial:** a Evolution usa um protocolo que viola os termos
  do WhatsApp. O número pode ser restringido, e a sessão pode cair e pedir o
  QR de novo. O risco aqui é menor que na referência (poucos contatos,
  internos, sem tráfego pago), mas existe. O número deve ser aberto no
  aparelho pelo menos a cada 14 dias. Trocar para a API oficial no individual
  é escrever outro adaptador contra o mesmo contrato, sem mexer no
  orquestrador.
- **Dado de negócio fora do chat web:** num grupo, a resposta fica visível
  para todos os membros, inclusive quem não tem acesso ao chat web. Liberar
  um grupo é decidir quem vê os dados. Isso fica registrado em
  `open-decisions.md` (O-18).
- **Infra:** um serviço novo pequeno (0,25 vCPU, 512 MB, ~US$ 10/mês), e a
  task do Jarvis sobe de 1 para 2 GB (o worker desenha os gráficos em PNG
  com o `vl-convert-python`). Tudo no Terraform do `sales_force_crm`, branch
  `feat/infra-jarvis`.
- **Um só número:** se a task da Evolution cair, o ECS sobe outra e a sessão
  volta do Postgres, sem QR. Enquanto isso, as mensagens chegam atrasadas, e
  nenhuma resposta se perde do lado do Jarvis.
- **Contrato conferido:** criar instância, configurar, apontar o webhook,
  pedir o QR e ler o estado foram conferidos contra a Evolution v2.3.7 local,
  sem número conectado. O envio e a recepção de verdade só serão conferidos
  com o chip.
