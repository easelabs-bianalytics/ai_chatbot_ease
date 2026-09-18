# Plano de execução

> Atualizado a cada fase concluída. Pendências externas em
> `docs/open-decisions.md`; decisões arquiteturais em `docs/adr/`.

Legenda: ✅ concluída · 🔲 não iniciada · ⏳ bloqueada por dependência externa

Toda fase termina com a suíte de testes passando e o resultado mostrado.
Commit só quando pedido.

## Fase 0 — Descoberta e decisões
**Status: ✅ concluída (2026-09-14)**

- [x] Estudo do projeto de referência `avaliacao_eleitores` (somente leitura)
- [x] Mapa "o que existe lá → o que vira aqui" aprovado
- [x] `git init` em `bi/`, `.gitignore`
- [x] `CLAUDE.md` com regras de trabalho e estrutura aprovada
- [x] `SPEC.md` e `SPEC_PILOT.md`
- [x] ADR-0001 a ADR-0013
- [x] `docs/open-decisions.md`, `docs/catalog-checklist.md`
- [x] Revisão: SQL gerado pela IA com as consultas validadas como referência (ADR-0014, substitui ADR-0009)
- [x] Rascunho do prompt de planejamento (`app/ai_orchestrator/prompts/planner_v1.md`)
- [x] Plano de testes (final deste documento)

## Fase 1 — Fundação
**Status: ✅ concluída (2026-09-14)**

- [x] `pyproject.toml` com uv, Python 3.12 (Django 5.2 LTS, DRF, Celery[redis], gunicorn, whitenoise, psycopg2-binary, python-dotenv, openai, sqlglot, PyYAML; dev: pytest, pytest-django) e `uv.lock`
- [x] Projeto Django em `app/config` (settings por variável de ambiente, proxy SSL, CSRF, Celery com `acks_late`)
- [x] **Banco da aplicação só lê `APP_*`** e recusa subir apontando para `*.rds.amazonaws.com` (`config/env.py`, ADR-0002) — o `bi/.env` já tinha credenciais da AWS com nomes desconhecidos
- [x] `config.settings_test`: suíte não carrega o `.env` e usa sempre o Postgres local
- [x] DRF com `SessionAuthentication` e `IsAuthenticated` por padrão
- [x] `docker-compose.yml`: `db` (5434), `redis` (6381), `analytics_db` (5435, sintético, com usuário `bi_readonly`) — portas fora das da referência
- [x] Usuário de leitura do banco sintético validado: `CREATE TABLE` recusado pelo próprio Postgres
- [x] `/api/health/` aberto e sem tocar o banco
- [x] `tests/conftest.py` com fixtures autouse (Celery eager, remoção de credenciais reais, bloqueio do cliente OpenAI)
- [x] Migrations aplicando, revertendo e reaplicando no banco local
- [x] `Dockerfile`, `railway.json`, `.env.example`, `.dockerignore`, `.gitattributes`
- [x] `README.md` e primeira versão do `ONBOARDING.md`
- [x] 24 testes automatizados passando

## Fase 2 — Modelos, canal e API do chat
**Status: ✅ concluída (2026-09-15)**

- [x] Apps `conversations`, `messaging`, `ai_orchestrator`, `datasource`
- [x] `Conversation`, `Message`, `AIReply`, `AICall`, `QueryRun`, `CatalogGap`
- [x] Idempotência por `client_message_id`, única **por conversa** (e não global como na referência): identificador repetido entre usuários não cruza resposta
- [x] `Channel` + `WebChannel` + `FakeChannel`; `services.py` com ingestão idempotente e entrega que registra falha em vez de estourar
- [x] API: criar e listar conversas, enviar pergunta (`202`; duplicada `200`), polling com `after`; conversa de outro usuário responde `404`
- [x] Admin: conversas, mensagens, respostas da IA com chamadas e consultas aninhadas (somente leitura) e fila de lacunas com ação de resolver
- [x] Migrations aplicando no banco local
- [x] 54 testes automatizados passando

## Fase 3 — Catálogo e acesso ao banco
**Status: ✅ concluída (2026-09-16)**

- [x] `knowledge/catalog.yaml`: schemas permitidos, tabelas e colunas bloqueadas, funções barradas, limites e notas de unidade
- [x] Permissão por **schema**, não tabela a tabela: enquanto D-04 não vem, o que protege é a lista de colunas bloqueadas e o GRANT do usuário de leitura
- [x] Loader de catálogo + referências, com `catalog_hash` das duas fontes; as 23 referências são extraídas com id e título
- [x] `sql_guard` (sqlglot): statement único, só SELECT, escrita em qualquer nó da árvore (inclusive CTE), schemas do sistema, schema fora do catálogo, tabela sem schema, tabela desaconselhada, coluna pessoal em qualquer posição, `SELECT *` em tabela sensível, funções administrativas, `FOR UPDATE`, limite com uma linha a mais
- [x] O SQL executado é o original, só embrulhado no limite — reemitir da árvore poderia mudar um cast e o número junto
- [x] `QueryExecutor` + `FakeQueryExecutor` programável + `PostgresReadOnlyExecutor` (transação somente leitura, `statement_timeout`, rollback, erros traduzidos)
- [x] Banco sintético no `analytics_db` com as 22 tabelas das referências e dados conferíveis à mão
- [x] Teste de integração contra o banco: escrita recusada pelo próprio Postgres, timeout, truncamento, erro legível
- [x] Comando `catalog_check` (com `--com-banco`)
- [x] 107 testes automatizados passando na primeira entrega (2026-09-15)
- [x] Usuário `bi_chatbot_ro` no RDS conferido pelo túnel: somente leitura, limites de 15 s e 10 s, escrita recusada pelo banco, 172 de 172 tabelas legíveis nos 6 schemas (D-01, 2026-09-16)
- [x] Comando `catalog_snapshot`: 170 tabelas e views do banco real em `app/knowledge/schema_snapshot.md`, com 64 colunas pessoais e as tabelas de staging do PBM omitidas (~13 mil tokens)
- [x] Catálogo alinhado ao documento de referência reescrito (96 consultas): schema `td`, `fato_cdd` liberada como fonte oficial, `remuneracao_fv` como schema previsto, colunas pessoais levantadas por varredura do banco real
- [x] `catalog_check --com-banco` contra o RDS: as 96 referências aprovadas e todas as tabelas existentes, exceto a de metas (prevista)
- [x] Validador: `COUNT(*)` deixou de ser tratado como `SELECT *` (recusava 10 referências)
- [x] Tabela ou schema inexistente vira "informação ainda não disponível" + lacuna, sem nova tentativa (regra do documento de referência)
- [x] 175 testes automatizados passando

## Fase 4 — Orquestrador com fakes
**Status: ✅ concluída (2026-09-15)**

- [x] `rules.py`: pedido de escrita, pedido de ajuda (montado do catálogo) e mensagem sem pergunta, sem chamar o modelo
- [x] Pipeline em `orchestrator.py`: idempotência → regras → planejamento → `sql_guard` → execução → redação → `grounding.py` → registro
- [x] `AIProvider` com `plan` e `answer`; `FakeAIProvider` (casa a pergunta com o título das referências), `FailingAIProvider` e providers programáveis em `tests/fakes/`
- [x] Correção única da consulta com o motivo da recusa ou o erro do banco; reescrita única da resposta quando a ancoragem reprova, com a tabela crua como saída final
- [x] `grounding.py`: todo número da resposta vem do resultado, da pergunta ou de filtro do SQL — literal do `SELECT` não ancora
- [x] "Não sei" cria `CatalogGap`; resultado vazio é resposta própria; falha da IA e do banco viram aviso legível com a mensagem marcada como falha
- [x] Histórico por conversa (`AI_HISTORY_MAX_MESSAGES`), e não por usuário: cada thread é um assunto
- [x] `tasks.py` (Celery) ligado à API, `provider_factory` e `executors/factory`
- [x] Ajustes vindos do arquivo de referências reescrito pelo time (de 23 para 37 consultas): ids no formato A01/B05 e consultas que terminam em comentário
- [x] 160 testes automatizados passando
- [x] Validado ao vivo contra o banco sintético: consulta aprovada, executada em 16 ms, resposta ancorada e auditoria completa

## Fase 5 — Provider real e chat local
**Status: ✅ concluída (2026-09-17)**

- [x] Modelo decidido: `gpt-5.6-terra` planeja e `gpt-5.6-luna` redige (ADR-0016, substitui ADR-0013)
- [x] `OpenAIProvider` (saída estruturada, custo por chamada com preço de cache) e `RetryingAIProvider` (backoff)
- [x] Cortes de contexto do ADR-0015: roteador por palavra-chave, dois temas completos, resumo do terceiro em diante, schema filtrado, redação sem o documento
- [x] Saída `PRECISO DA SEÇÃO`: a IA pede o documento inteiro em vez de inventar a regra que faltou
- [x] Teto de gasto mensal (O-14): confere antes de chamar o modelo e responde com texto próprio
- [x] `prompts/planner_v1.md` ligado ao provider, com as seções do documento, o schema filtrado, o histórico e a data de hoje injetados
- [x] `prompts/answerer_v1.md`: tom e personalidade aprovados (número primeiro, período e recorte explícitos, pt-BR, sem emoji, sem cálculo no texto)
- [x] `Plan.user_message`: orientação da IA em "não sei" e "fora de escopo" (forecast, meta indisponível), trocada pelo texto padrão se citar número
- [x] `.env.example` alinhado ao ADR-0016 e `AI_PROVIDER_MAX_ATTEMPTS` passando a ser lido de verdade
- [x] `provider_factory` (`AI_PROVIDER=openai` liga o real, embrulhado no retry)
- [x] `chat_local` (`--fake-ai`, `--fake-db`, `--pergunta`, `/nova`, `/sql`, `/status`, `/sair`), mostrando seções, tokens, cache, custo e tempo
- [x] Primeira conversa real contra o RDS em 2026-09-17: referência B11 usada, resposta ancorada, US$ 0,03 e 12 s
- [x] Prova de fogo com 20 casos difíceis contra a IA e o RDS reais (2026-09-17): 19 aprovados, 1 revisão manual, 0 bloqueadores
- [x] Custo real medido: **US$ 0,041 por pergunta** e 17 s em média (preço calibrado pela fatura: a tabela publicada dava US$ 2,00 de entrada no Terra, a cobrança saiu como US$ 2,50)
- [x] Esforço de raciocínio fica em `medium`: a saída média é de 288 tokens, então baixá-lo economizaria quase nada
- [x] Achados da rodada: a IA comparava nome de rede com `=` (corrigido no prompt) e uma rede tem duas raízes de CNPJ (corrigido no documento de referência, O-15)
- [x] 267 testes automatizados passando

## Fase 6 — Interface web
**Status: ✅ concluída (2026-09-18)**

- [x] Desenho análogo ao da Indicação de PDVs e ao ui-system oficial, com o logo da Ease Labs (ADR-0017)
- [x] App `web`: página única servida pelo Django, sem build nem framework de front
- [x] Login por sessão pela API, com CSRF inclusive no login e mensagem única para usuário ou senha errados
- [x] Lista de conversas, nova conversa, chat com polling (retoma a espera se a página for reaberta)
- [x] Sugestões de pergunta na conversa vazia, "consultando" com tempo decorrido
- [x] Fonte da resposta visível: referência usada, linhas, corte, tempo no banco, momento e o SQL com realce e botão de copiar; custo e tokens só para a equipe
- [x] Respostas de esclarecimento, "não disponível", fora de escopo e falha com aparência própria; falha com "perguntar de novo"
- [x] Markdown da resposta renderizado com escape antes da formatação (nada do modelo vira tag)
- [x] `Message.in_reply_to` liga a resposta à pergunta que a gerou
- [x] Celular: lista vira gaveta, alvos de 44 px, campo sem zoom automático
- [x] Verificado no navegador (Edge) com perguntas reais contra o RDS, no computador e no celular
- [x] Redação: não repete na frase os números da tabela e destaca o último mês fechado quando o mês atual é parcial
- [x] Ajustes pedidos após a primeira visita (2026-09-18): índigo no lugar dos gradientes (fica só a faixa lateral da conversa), fonte recolhida em "Ver fonte e consulta", aviso "a IA pode cometer erros" no rodapé do campo
- [x] Projetos (pastas), arquivar e excluir conversas, com menu ⋯ e janelas de confirmação (ADR-0018); excluir é lógico e preserva a auditoria
- [x] Layout mais enxuto (2026-09-18): barra superior removida e a marca foi para o topo da sidebar; sidebar recolhe para uma trilha de 64 px (Ctrl+B, lembrado no navegador); cartão de cabeçalho da conversa removido; conversa numa coluna de leitura de 860 px em vez da largura da tela; título menor e cartões sem sombra, para sair do ar de banner
- [x] Tema escuro (2026-09-18): claro, escuro ou o do sistema, escolhido no menu do usuário e lembrado no navegador. A escala de cinza inverte e os componentes seguem iguais; o gráfico lê as cores dos mesmos tokens e é redesenhado na troca. Decidido antes da primeira pintura, no `<head>`, para a tela não piscar branca
- [x] Menu do usuário deixou de sair espremido com a sidebar recolhida (o `overflow: hidden` da lateral cortava o menu, e a largura de 64 px quebrava o texto letra a letra)
- [x] Barra de fonte ("Ver fonte e consulta" + "Baixar Excel") discreta no repouso e cheia no hover, no foco pelo teclado ou quando aberta — com o mesmo peso do texto ela disputava a leitura com o número; o botão destacado de planilha e o celular (sem hover) ficam sempre visíveis
- [x] Tela inicial cumprimenta pelo nome e pela hora ("Boa tarde, Rubens"), com uma de quatro linhas de convite sorteada a cada conversa nova — a mesma frase todo dia some da vista na segunda semana
- [x] Login em azul-noite (`--gray-950`) com halo índigo atrás do cartão: o índigo puro no fundo inteiro puxava para o roxo e brigava com o índigo dos botões
- [x] Mascote da sidebar dentro de um selo quadrado índigo-claro, no lugar do ícone solto
- [x] Marca da sidebar em duas linhas (logotipo da Ease em cima, mascote + Jarvis embaixo): lado a lado os dois se espremiam
- [x] Faixa da conversa ativa em índigo sólido, sem o gradiente verde→índigo que virava borrão em 3 px
- [x] Login centralizado na tela, sobre o índigo da marca, com o cartão branco em destaque
- [x] Favicon maior: o mascote passou a ocupar 94% do lado, em vez de 77%
- [x] Tabela da resposta sai completa: a redação recebe até 50 linhas e mostra todas; só resume quando o resultado não coube inteiro, apontando a planilha
- [x] Gráfico mais simples (2026-09-18): número na ponta da barra em vez de eixo de valores, nomes das categorias legíveis, barra com altura própria, corte em 14 categorias com aviso de quantas ficaram — 31 barras num cartão viravam fiapos
- [x] O Jarvis sabe que é o Jarvis: o nome no vocativo ("Jarvis, quais CDs...") nunca entra na consulta como filtro
- [x] Auréola do mascote parou de girar 360° (passava pela vertical e parecia atravessar o corpo): anel fixo e inclinado, com um satélite correndo nele e contorno branco separando os dois
- [x] Resolução de nomes e verificação do resultado vazio (ADR-0022): nome próprio entra por pedaço no `ILIKE`, comparação entre nomes resolve primeiro e mede depois (E27, com caso de validação), e "zero linhas" dispara uma consulta de verificação em vez do aviso seco — as duas regras foram para o preâmbulo do documento e para o núcleo do contexto, que vai em toda pergunta
- [x] Mascote do Jarvis (2026-09-18): cápsula índigo com viseira e olho verde, redesenhado em SVG inline a partir do PNG da IA de imagem (`docs/brand/`) e animado por CSS — respira na tela inicial, varre a viseira enquanto pensa, acelera quando consulta o banco e dá um pulo quando responde; favicon gerado do mesmo desenho
- [x] Nome do produto: **Jarvis**, copiloto de dados (2026-09-18; antes "Assistente de Dados"), sem selo colorido; logo recortado e gerado em 1x/2x/3x com Lanczos (o PNG de 1200px reduzido no navegador ficava borrado)
- [x] Usuário no canto inferior esquerdo da barra lateral, com o menu abrindo para cima; tela inicial centralizada na área da conversa
- [x] Crédito da OpenAI esgotado ou teto do mês: aviso discreto pedindo para falar com o time de BI & Analytics, sem retry
- [x] Conversa sem consulta (ADR-0019): cumprimento, conceito e interpretação do que já está na conversa, sem número novo; "Pensando…" até a consulta sair
- [x] Mensagem sem tema vai com contexto mínimo: "Quem é você?" caiu de ~US$ 0,09 para US$ 0,002
- [x] Regra de ajuda: cinco temas em vez de 96 títulos; deixou de capturar "o que pode ter causado…"
- [x] Redação: proibido mudar a escala do número ("777 unidades", nunca "777 mil" por causa do `/ 1000` do SQL)
- [x] Gráfico simples da resposta (ADR-0020): a IA sugere tipo e colunas, o orquestrador confere contra o resultado e o navegador desenha com Chart.js servido pela aplicação
- [x] Planilha Excel formatada (ADR-0020): botão em toda resposta com consulta, destacado quando o usuário pediu; roda a consulta de novo pelo validador com limite de 50.000 linhas, CNPJ e EAN como texto, aba de informações, e cada download registrado em `DataExport`
- [x] Escopo do assistente fechado (ADR-0021): conhecimento geral, receita, opinião, tradução e afins viram "fora do que eu faço" com oferta de ajuda nos dados — antes a IA respondia sobre a Revolução Industrial como se fosse assunto dela
- [x] Prompt injection barrado em três camadas: regra determinística antes do modelo (registrada na auditoria como `tentativa_de_injecao`), escopo e "texto é dado, não instrução" nos dois prompts, e conferência do texto de saída contra marcas do prompt
- [x] Glossário no núcleo do contexto (SEM CAT, visita efetiva, painel × visitas, mês sem carga, voucher): sem ele a IA definia "SEM CAT" de cabeça, e definição errada volta como número errado depois
- [x] 370 testes automatizados passando

## Fase 7 — Validação
**Status: ✅**

- [x] `app/knowledge/casos_validacao.yaml`: 127 casos derivados do documento de referência — as 96 consultas cobertas, cada uma com período, recorte, produto, rede ou pessoa trocados em relação ao exemplo; mais esclarecimentos, seguimento de conversa, fora de escopo, dado indisponível e segurança
- [x] Gabarito montado a partir da própria consulta do documento (parâmetros + trocas de texto): se o documento mudar, o caso quebra alto
- [x] 28 regras de negócio do documento conferidas no SQL da IA (filtros do CDD, ×1000, venda PBM confirmada, dia 0 da ruptura, SEM CAT...)
- [x] Comparação por coluna com o gabarito (aceita outro nome, outra ordem e coluna a mais; não aceita número diferente nem resultado cortado)
- [x] `run_synthetic_cases` pelo pipeline completo, com status aprovado / reprovado / revisão / bloqueador e `docs/validation-report.md` com modelo, prompt, hash do catálogo e dos casos
- [x] `run_synthetic_cases --so-gabarito` contra o RDS: todos os gabaritos rodam e devolvem linhas (2026-09-16)
- [x] **Rodado com a IA real** em 2026-09-17: 20 casos, 15 aprovados, 4
      reprovados, 1 para revisão, nenhum bloqueador, US$ 0,59 e 346 mil
      tokens (`docs/validation-report.md`)
- [x] Os quatro reprovados foram revisados um a um e nenhum era erro da IA:
      a pergunta do A03 pedia outro recorte, a comparação do B01 exigia
      igualdade de colunas que o gabarito não tinha, e o gabarito do C34
      ignorava a segunda raiz de CNPJ da rede. Os casos e o documento foram
      corrigidos; o de revisão (C20) tinha duas respostas certas
- [x] Decidido em 2026-09-18: **a suíte inteira não roda de rotina.** As 127
      perguntas com a IA real custam por volta de US$ 5 e repetem o que os
      testes automatizados já cobrem de graça. Ela fica para marcos —
      troca de modelo, reescrita do documento de referência, mudança no
      pipeline —, e no dia a dia usa-se o recorte: `--caso`, `--grupo` ou
      `--so-gabarito`, que não chama a IA
- [x] 394 testes automatizados passando

## Fase 8 — Relatório
**Status: ✅**

- [x] `reporting/services.py`: agrega a auditoria que já existe (FR-15) —
      nenhuma tabela nova e nenhum contador incrementado na hora da resposta,
      que divergiria do registro na primeira falha de gravação
- [x] `bi_report` no terminal, com `--dias`, `--desde/--ate` e `--csv`
      (uma linha por dia, para abrir na planilha). Não chama a IA nem toca no
      banco de negócio: roda a qualquer hora, sem custo
- [x] Cobre o FR-16: uso (perguntas, pessoas, conversas, planilhas), como
      cada pergunta terminou, consultas corrigidas e com erro, respostas
      reescritas por ancoragem, tempo até a resposta (mediana, p95 e a pior)
      e custo — total, por pergunta e projetado para 30 dias
- [x] Lacunas do catálogo em aberto, com a pergunta e o motivo: é a lista de
      trabalho do time de BI que sai pronta do relatório
- [x] 13 testes fixam a aritmética: o que entra na janela, o que fica de
      fora, como o p95 é contado e o agrupamento diário no fuso local
- [ ] **Primeira leitura (2026-09-18) acusou p95 de 28,2 s, acima da meta de
      20 s do SPEC** — mediana de 11,9 s e uma pergunta de 102 s. A suspeita
      é a pergunta que cruza áreas, que leva duas seções do documento e uma
      segunda chamada ao modelo. Investigar antes do deploy

## Fase 9 — Deploy
**Status: 🔲** (⏳ D-02) · acesso ao console da AWS recebido em 2026-09-17 ·
infraestrutura descrita em Terraform

### O que vai ao ar

O app deixa de ser local: o que hoje são três processos no Windows mais dois
contêineres de `docker-compose` vira a lista abaixo. Nada aqui é opcional —
onde houver escolha, ela está marcada como decisão.

| Peça | O que é | Provisiona | Custo/mês (sa-east-1, conferir na calculadora) |
|---|---|---|---|
| **ECR** | um repositório; uma imagem só, dois comandos diferentes | Terraform | ~US$ 1 |
| **ECS Fargate — `web`** | Gunicorn + WhiteNoise, 0,25 vCPU / 0,5 GB | Terraform | ~US$ 9 |
| **ECS Fargate — `worker`** | Celery (`-P solo` basta: uma pergunta por vez, 30 s cada) | Terraform | ~US$ 12 |
| **ALB + ACM** | HTTPS, healthcheck em `/api/health/` | Terraform | ~US$ 20 |
| **Redis** | fila do Celery — **sim, é serviço externo**, ver abaixo | Terraform | ~US$ 15 |
| **Banco da aplicação** | conversas, usuários, sessões, auditoria — ver abaixo | Terraform + DBA | US$ 0 a 25 |
| **Saída para a internet** | NAT ou IP público nas tasks, para chamar a OpenAI | Terraform | US$ 0 ou ~US$ 33 |
| **Secrets Manager** | 4 segredos | Terraform | ~US$ 2 |
| **CloudWatch Logs + alarmes** | um log group por serviço, retenção 30 dias | Terraform | ~US$ 3 |
| **OpenAI** | fora da AWS, cartão pré-pago (ADR-0016) | manual | US$ 10 a 30 |

Ordem de grandeza: **US$ 70 a 120/mês**, sendo NAT e ALB os dois maiores
fixos — e os dois com alternativa mais barata, descritas abaixo.

### Redis: o que muda

A fila do Celery hoje é um contêiner local. Em produção ela precisa de um
serviço de verdade, porque é ela que segura a pergunta entre o clique do
usuário e a resposta do worker.

- **ElastiCache for Redis, nó único `cache.t4g.micro`** — recomendado. Sem
  réplica: a fila é pequena e uma mensagem perdida significa uma pergunta
  reenviada, não um dado corrompido.
- ElastiCache **Serverless** foi descartado: a cobrança mínima de
  armazenamento fica acima de US$ 80/mês para um uso que cabe em megabytes.
- Redis em contêiner no próprio ECS foi descartado: sem volume persistente,
  todo deploy derrubaria as perguntas em voo, e o Fargate não garante que o
  worker e o Redis fiquem na mesma rede local.
- [ ] Definir `CELERY_BROKER_URL` apontando para o endpoint do ElastiCache,
      com `rediss://` (TLS em trânsito ligado) e AUTH token no Secrets Manager
- [ ] SG do Redis liberando 6379 só para o SG da aplicação

### Banco da aplicação e o schema do projeto (O-16)

O banco de negócio (`easelabs`, na instância `cockpit-prod-db`) **nunca**
entra em `DATABASES` — é a trava do ADR-0002, e ela existe para que um
`migrate` não crie tabelas do Django dentro dele. O app precisa do banco
dele, com escrita.

Três caminhos, do mais isolado ao mais barato:

1. **Instância RDS própria** (`db.t4g.micro`, 20 GB): isolamento total,
   backup e janela de manutenção independentes. ~US$ 15 a 25/mês.
2. **Database separado na instância existente** (`CREATE DATABASE jarvis`) —
   **recomendado**. No PostgreSQL não há acesso entre databases sem FDW, então
   o isolamento é quase o da opção 1, sem custo novo. Exige aval da DBA,
   porque a instância é de produção de outro produto (`cockpit-prod`).
3. ~~Schema dentro do database `easelabs`~~ — **descartado**: o usuário com
   escrita passaria a se conectar no mesmo database dos dados de negócio, e a
   garantia de somente leitura (ADR-0008) deixaria de ser estrutural para
   virar questão de acerto nos `GRANT`.

Desenho proposto para a opção 2 (vale igual na 1):

```sql
CREATE DATABASE jarvis;                      -- separado do easelabs
\c jarvis
CREATE SCHEMA jarvis;                        -- não usar o public
CREATE ROLE jarvis_app LOGIN PASSWORD :senha;   -- dono, escreve
CREATE ROLE jarvis_ro  LOGIN PASSWORD :senha;   -- time de BI, só lê a auditoria
ALTER SCHEMA jarvis OWNER TO jarvis_app;
GRANT USAGE ON SCHEMA jarvis TO jarvis_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE jarvis_app IN SCHEMA jarvis
  GRANT SELECT ON TABLES TO jarvis_ro;       -- vale para as tabelas futuras
REVOKE ALL ON SCHEMA public FROM PUBLIC;
```

As 18 tabelas do Django passam a viver em `jarvis`, por área:

| Área | Tabelas | Para quê |
|---|---|---|
| Acesso | `auth_user`, `auth_group*`, `auth_permission`, `django_session` | quem entra e o que vê |
| Conversas | `conversations_conversation`, `conversations_project`, `messaging_message` | o histórico do usuário |
| Auditoria | `ai_orchestrator_aireply`, `ai_orchestrator_aicall`, `ai_orchestrator_cataloggap`, `datasource_queryrun`, `datasource_dataexport` | a decisão, o custo, o SQL que rodou e cada download |
| Infra do Django | `django_migrations`, `django_content_type`, `django_admin_log` | versão do schema e trilha do Admin |

- [ ] **Pedido à DBA (único bloqueio hoje)**: `ALTER ROLE rubens_dba CREATEDB CREATEROLE;`
      — conferido em 2026-09-18, ele não tem nenhum dos dois nem `CREATE` no
      `easelabs`. Script e explicação em `infra/app-db/01_pedido_dba_permissoes.sql`;
      a lista completa de acessos que faltam está em `docs/permissoes-pendentes.md`
- [ ] Decidir opção 1 ou 2 com a DBA (O-16)
- [x] Script de criação pronto e **validado num PostgreSQL 16**:
      `infra/app-db/02_criar_banco_jarvis.sql` (roles, database, schema
      `jarvis`, `search_path` e leitura para o time de BI); senhas entram por
      parâmetro, nunca no arquivo
- [ ] `search_path=jarvis` na conexão (`OPTIONS: {"options": "-c search_path=jarvis"}`)
- [ ] Ajustar a trava do ADR-0002: hoje recusa qualquer host `*.rds.amazonaws.com`; deve recusar só o host do banco de negócio
- [ ] `migrate` como task avulsa do ECS **antes** de trocar a versão do serviço `web`
- [ ] Backup: confirmar que o snapshot da instância cobre o database novo, e restore testado uma vez
- [ ] `jarvis_ro` entregue ao time de BI para consultar a auditoria sem passar pelo app

### Usuários

O acesso é usuário e senha do Django (ADR-0011), mas quem pode entrar sai do
cadastro que a empresa já mantém: **`trade_fv.usuario`** (singular; as
colunas são `id`, `usuario`, `nome`, `email`, `role`).

- [x] Comando `sincronizar_usuarios` (2026-09-18): lê `trade_fv.usuario` pelo
      papel, cria e atualiza `auth_user`, é idempotente, nunca toca em senha
      de quem já existe e só desativa quem ele mesmo criou — os sincronizados
      entram no grupo `cadastro-empresa`, então a `demo` e acessos temporários
      não caem junto. Aceita `--arquivo` (CSV) enquanto o GRANT não sai.
- [x] Os quatro administradores criados no banco local a partir de
      `infra/app-db/usuarios_iniciais.csv`
- [x] Decidido em 2026-09-18: **o projeto não depende de schema de outro
      sistema**. A lista inicial entra por arquivo e a manutenção é pelo Admin
      do Django; nada é pedido no `trade_fv` (a opção `--do-banco` do comando
      fica desligada, caso um dia se queira retomar)
- [ ] Definir como a senha nasce: hoje o usuário criado fica sem senha
      utilizável (ninguém entra até definir uma, com `changepassword`).
      Decidir entre senha inicial de uso único e SSO/OIDC no lugar do login
      local
- [ ] Rodar `sincronizar_usuarios --desativar-ausentes` no deploy e, depois,
      periodicamente (quem sai da empresa precisa sair daqui)
- [ ] Usuários internos autorizados cadastrados (D-05)

### Rede

- [ ] VPC do RDS; tasks em subnet privada
- [ ] **Saída para a OpenAI** (D-02, ADR-0016) — decisão entre:
      **NAT Gateway** (~US$ 33/mês + tráfego, tasks sem IP público) ou
      **subnet pública com IP público na task** (US$ 0, exposição contida
      pelo security group, que não aceita conexão de entrada)
- [ ] ALB **interno** (só rede corporativa/VPN) ou público com HTTPS —
      decisão; interno é o padrão para ferramenta interna
- [ ] SGs: ALB ← rede corporativa; app ← ALB; RDS ← app (5432, SSL); Redis ← app (6379)
- [ ] Regra no SG do RDS de negócio liberando o SG da aplicação, com SSL

### Aplicação

- [ ] `collectstatic` no build da imagem (WhiteNoise com manifest) e `DEBUG=0`
- [ ] `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` e `SECURE_PROXY_SSL_HEADER` (já existem em `settings.py`, faltam os valores)
- [ ] Segredos no Secrets Manager: chave da OpenAI, senha do `bi_chatbot_ro`, senha do `jarvis_app`, `SECRET_KEY`
- [ ] Healthcheck do ALB em `/api/health/` sem redirect forçado para HTTPS (o `SECURE_SSL_REDIRECT` fica desligado por isso)
- [ ] Investigar o p95 de 28,2 s medido em 2026-09-18 (`bi_report`), acima da meta de 20 s do SPEC: ver quanto é a chamada ao modelo e quanto é o banco antes de culpar o palpite
- [ ] Conexão com o RDS validada de dentro da VPC com o usuário de leitura

### Terraform

- [ ] Estado remoto em S3 com lock (o lockfile nativo do S3 dispensa a tabela no DynamoDB)
- [ ] `infra/terraform/` com módulos: `rede` (data sources da VPC existente), `ecr`, `ecs`, `alb`, `redis`, `banco`, `segredos`, `observabilidade`
- [ ] O que **não** é Terraform, e por quê: `CREATE DATABASE`/`ROLE` (a DBA faz, ou o provider `postgresql` com credencial de administrador — decisão), as migrações do Django (task de deploy) e a sincronização de usuários (comando)
- [ ] Um `terraform plan` limpo revisado antes do primeiro `apply`

### Observabilidade e custo

- [ ] Log group por serviço, retenção de 30 dias
- [ ] Alarme de 5xx no ALB e de task derrubada pelo healthcheck
- [ ] Alerta quando o log registrar "Créditos da OpenAI esgotados" (metric filter): hoje o usuário vê o aviso discreto e ninguém do time é avisado
- [ ] AWS Budgets com aviso em 80% do orçamento combinado
- [ ] Limite mensal na OpenAI ajustado ao volume (decisão de 2026-09-18: manter US$ 10 no início; ~US$ 30 para 25 perguntas/dia) e `AI_MONTHLY_BUDGET_USD` um pouco abaixo dele (US$ 9,50 com o limite de US$ 10)
- [ ] Conta da OpenAI em créditos pré-pagos com **recarga automática desligada**: é o que garante que nada seja cobrado do cartão além do crédito comprado
- [ ] Acompanhar na auditoria as respostas com regra `tentativa_de_injecao`: poucas são curiosidade de usuário interno, muitas e repetidas merecem conversa com o time (ADR-0021)

### Retenção

- [ ] Política de retenção do histórico definida (O-08) — hoje a exclusão é lógica e o banco cresce ~15 a 35 MB/mês a 50 perguntas/dia
- [ ] Retenção do `result_sample` das consultas com gráfico: guarda o resultado inteiro (até 500 linhas), ~50 a 100 MB/mês a 50 perguntas/dia

---

## Plano de testes

Regra geral: a suíte (`uv run pytest`) nunca acessa rede, OpenAI ou o RDS.
`tests/conftest.py` remove `AI_PROVIDER_API_KEY` e `ANALYTICS_DATABASE_URL`
do ambiente por fixture autouse, então valores do `bi/.env` nunca chegam aos
testes. Cada teste traz na docstring o incidente que previne.

| Camada | O que prova | Tipo |
|---|---|---|
| `sql_guard` | Escrita, DDL, múltiplos statements, CTE com DML, catálogos do sistema, colunas bloqueadas em qualquer posição, `SELECT *` em tabela sensível, funções perigosas, `FOR UPDATE`, LIMIT e truncamento | unit |
| Referências | Q01–Q51 parseáveis e aprovadas pelo `sql_guard` | unit |
| `grounding.py` | Formatos pt-BR/en, percentuais, milhares; literal no `SELECT` não ancora número | unit |
| `rules.py` | Pedido de escrita, ajuda, mensagem inválida sem chamar o modelo | unit |
| Orquestrador | Cada ramo com providers programáveis e `FakeQueryExecutor`: resposta, esclarecimento, não sei, vazio, truncado, correção única, falha da IA, falha do banco, idempotência | unit |
| `OpenAIProvider` | Contratos JSON, erro de API, JSON inválido, custo com cache (cliente mockado) | unit |
| `RetryingAIProvider` e tarefa Celery | Backoff, esgotamento, execução eager | unit |
| API do chat | Login obrigatório, isolamento entre usuários, idempotência (`202` → `200`) | integration |
| `PostgresReadOnlyExecutor` | Contra o `analytics_db` local com usuário de leitura: escrita recusada pelo próprio banco, timeout, truncamento | integration |
| Casos de validação | Cobertura das 96 referências, gabaritos montáveis e aprovados pelo validador, regras coerentes com os gabaritos | unit |
| Avaliador da suíte | Cada status (aprovado, reprovado, revisão, bloqueador) com IA e banco programados; comparação de resultados | unit |
| `run_synthetic_cases` | Comportamento com a IA real contra o banco real | fora da suíte, gera relatório |
