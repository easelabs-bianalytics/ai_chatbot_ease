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
- [x] **Banco da aplicação só lê `APP_*`** e recusa subir apontando para `*.rds.amazonaws.com` (`config/env.py`, ADR-0002) — o `bi/.env` já tinha credenciais da AWS com nomes desconhecidos. *Revisto na Fase 9 (passo 8): a trava por host vale só sob teste; em produção a garantia é o schema `jarvis` e o privilégio da role*
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
- [x] Continuações depois da resposta (2026-09-18): a redação propõe de duas a três perguntas curtas do próximo passo da investigação, e a tela oferece em um clique. Saem na mesma chamada que já se paga; o orquestrador limpa as longas, as repetidas e as que só devolvem a pergunta que acabou de ser feita
- [x] Busca no histórico: olha o título **e** o texto das mensagens, porque quem procura "ruptura" lembra do que perguntou, não de como a conversa ficou nomeada
- [x] Ajuste do gráfico pela conversa ("muda para barras", "só os 5 primeiros"): regra determinística, sem consulta e sem chamada ao modelo — os números já estão na tela. Só dispara com gráfico à vista e mensagem curta e inequívoca, para não sequestrar pergunta de dado
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
- [x] **Primeira leitura (2026-09-18) acusou p95 de 28,2 s, acima da meta de
      20 s do SPEC** — mediana de 11,9 s e uma pergunta de 102 s.
      Investigado em 2026-09-21: o tempo é todo do modelo (banco com mediana
      de 0,3 s), e o gargalo é a chamada de `fix` que carrega o documento
      inteiro — 41,0 s de média contra 12,8 s sem ele. Números e o que
      decidir estão em "Depois do deploy"

## Fase 9 — Deploy
**Status: ✅ concluída (2026-09-21)** · os onze passos fechados. O Jarvis
está em produção em `https://jarvis.easelabs.app.br`, com o schema `jarvis`
no `easelabs`, alarme de 5xx e de task sem host saudável, e a infra mesclada
na `main` do `sales_force_crm`

### Onde estamos

| Passo | Situação |
|---|---|
| 0 — Pré-condições da máquina | ✅ Terraform 1.16.2, túnel, AWS CLI, Docker |
| 1 — Role, schema e secrets | ✅ schema `jarvis` no `easelabs`, role `jarvis_app`, 12 secrets, 18 tabelas migradas |
| 2 — Escrever os `.tf` | ✅ 13 arquivos, 588 linhas, todas do Jarvis; branch empurrada |
| 3 — `terraform plan` | ✅ com refresh, sem `AccessDenied`; plano só do Jarvis: **12 adições, 1 mudança, 0 destruições** |
| 4 — `apply` com alvo | ✅ 11 recursos criados + `rds-sg` alterado; a task está no ar com o nginx |
| 5 — CNAME de validação | ✅ criado no registro.br; conferido no DNS público |
| 6 — Certificado `ISSUED` | ✅ emitido e anexado ao listener HTTPS |
| 7 — CNAME final | ✅ `jarvis.easelabs.app.br` → ALB no DNS público, certificado válido |
| 8 — Imagem real | ✅ `cockpit-prod-jarvis:2ea453d` no ECR, linux/amd64, 83 MB |
| 9 — Bump da imagem | ✅ task definition `cockpit-prod-jarvis:2` com `2ea453d`, alvo saudável no ALB |
| 10 — Migrations e usuários | ✅ 19 tabelas no `jarvis`, 4 administradores criados |
| 11 — Testar e fechar | ✅ login por código, pergunta com número conferido, planilha e gráfico; merge feito |

**A regra para daqui em diante, da Natália (2026-09-21): separar as nossas
mudanças do resto e subir só as nossas.** Todo `apply` desta branch é com
`-target` — a lista está no passo 3. Um `apply` sem alvo faria três coisas
que não são nossas; ver o passo 3.

**Pendências que dependem de outras pessoas** — o que é nosso fica dentro
do passo em que acontece, não aqui:

| Pendência | Quem | O que destrava |
|---|---|---|
| Empurrar o código de IAM aplicado em 2026-09-21 (`rubens_admin`): está no state, mas em nenhuma branch, e a nossa base ainda tem as policies antigas | Natália | um `apply` sem alvo deixar de ser perigoso, e o merge do passo 11 |
| Confirmar se o Poetry do Dockerfile é exigência literal | Natália | o Dockerfile do passo 8 |

Conferido contra o Terraform vivo do cockpit em 2026-09-21.

Duas coisas para ter em mente antes de qualquer comando:

1. **A infraestrutura não sai deste repositório.** Ela é descrita num Terraform
   único em `D:\Projetos\sales_force_crm\infra\`, que já tem 73 recursos em
   produção (VPC, ALB, cluster ECS, RDS e cinco services). O Jarvis entra lá
   como mais um service. Este repositório só produz a imagem e os scripts SQL.
2. **O Jarvis é um schema no `easelabs`**, não um banco novo — igual a
   `cockpit`, `trade_fv`, `app_api` e `app_pipelines`. A garantia do ADR-0002
   passa a ser privilégio de banco (`search_path` fixo na role, sem `CREATE`
   fora do schema, sem `CREATEDB`) em vez de topologia.

### Os quatro documentos que mandam

Este plano não inventa procedimento: ele traduz para o Jarvis o que já está
escrito no repositório de infra. Em caso de divergência, **o documento vence**.

| Documento | O que ele governa |
|---|---|
| `sales_force_crm/demo_deploy_app/PASSO_A_PASSO_DEPLOY_TERRAFORM.md` | **o passo a passo**: quais recursos declarar, em que arquivo, e a ordem de execução validada ponta a ponta |
| `sales_force_crm/CLAUDE.md` (seção Terraform) | as regras de qualquer mudança em `infra/`, inclusive o snapshot antes de mexer no banco de produção |
| `sales_force_crm/infra/README.md` | o que já existe na conta, o banco único `easelabs`, secrets e acesso por SSM |
| `sales_force_crm/Dockerfile` | o padrão multiestágio de imagem, pedido pela DBA |

O modelo a copiar é o **`trade_fv`**: é o serviço mais recente e aparece em
todos os arquivos que o Jarvis precisa tocar.

### As regras (CLAUDE.md e passo a passo do `sales_force_crm`)

1. **Toda mudança de infra passa pelo Terraform**: editar `.tf` → `plan` → ler
   o diff → `apply`. Nunca criar ou alterar recurso no console ou por `aws`
   CLI solto. As únicas exceções são as que o próprio documento marca como
   manuais: DNS no registro.br, `CREATE ROLE`/secrets do banco, e
   `docker build`/`push`.
2. **Nunca `apply` sem `plan`, e ler o diff de verdade.** Mudança em algo que
   você não tocou é drift: para e investiga, não aplica por cima.
3. **Commit e push do `.tf` antes do `apply`, não depois.** O state remoto é
   compartilhado, mas o `.tf` só é fonte da verdade se estiver no git.
4. **Serviço novo é Terraform-only desde o primeiro dia, sem
   `ignore_changes`.** A exceção existe só para o `cockpit-app`. **Consequência
   direta para nós: o passo "atualizar o serviço" não é `update-service` por
   CLI nem pelo console — é editar a variável da imagem, `plan`, `apply` e
   commitar.**
5. **Rodar `plan` periodicamente**, mesmo sem mudança, como detector de drift.
6. **Se alguém mexer na mão numa emergência, reconciliar na hora**
   (`import`/`state mv` até o `plan` limpar).
7. **Banco de produção: snapshot manual antes de qualquer mudança** — regra 6
   do `CLAUDE.md`, que não está na lista do passo a passo e ficou de fora da
   primeira versão deste plano. Vale para o `migrate` do passo 10. Os
   `CREATE ROLE`/`CREATE SCHEMA` e o primeiro `migrate` (passo 1) rodaram
   **sem** snapshot — eram só acréscimos num schema novo, sem tocar em dado
   existente, mas a regra não abre exceção e daqui em diante vale:

   ```bash
   aws rds create-db-snapshot --region sa-east-1 \
     --db-instance-identifier cockpit-prod-db \
     --db-snapshot-identifier cockpit-prod-db-antes-jarvis-<o-que>-<AAAAMMDD>
   aws rds wait db-snapshot-available --region sa-east-1 \
     --db-snapshot-identifier cockpit-prod-db-antes-jarvis-<o-que>-<AAAAMMDD>
   ```

   E quando a mudança for Terraform no próprio RDS: o `plan` tem de dizer
   *update in-place*, nunca *replace* nem *destroy*.

E a regra de nome: todo recurso se chama `cockpit-prod-jarvis-*`. Até
2026-09-21 ela era também uma exigência de permissão (a policy antiga do
usuário `rubens` era escopada por esse prefixo); com o `AdministratorAccess`
virou só convenção — mas é a convenção da casa, e é o que deixa claro, no
console, de quem é cada recurso.

### Como commitar daqui em diante

São **dois repositórios**, e a maior parte das mudanças mexe só no primeiro.

| Repositório | Onde | Branch | O que vai nele |
|---|---|---|---|
| **Jarvis** (`bi/`) | `easelabs-bianalytics/ai_chatbot_ease` | `main` — é a convenção do histórico até aqui | o app inteiro: código, tela, prompts, catálogo, migrations, docs, scripts SQL |
| **`sales_force_crm`** | `easelabs-analytics/sales_force_crm` | **sempre a `feat/infra-jarvis`** — uma branch só, de vida longa; merge na `main` mais tarde | só `infra/` — o que o Jarvis precisa na AWS |

**A branch do `sales_force_crm` (decisão do Rubens, 2026-09-21):** tudo o que
é do Jarvis — bump de imagem, variável, secret, alarme — é commitado na
**`feat/infra-jarvis`**. Nada de branch nova por mudança e nada de commit
direto na `main`: o app ainda vai mudar de estrutura, e a `main` é
compartilhada com o time do Cockpit. O merge na `main` vem depois, combinado
com a Natália e no padrão dela (commit `merge: incorpora feat/infra-jarvis em
main`, como os de `951618b` e `2f03e64`).

Como a Natália trabalha, conferido no histórico em 2026-09-21: o dia a dia
dela vai **direto na `main`** (inclusive infra, como o IAM `7a22750` e o bump
do `sync` `01dc9cd`); trabalhos maiores vão numa branch de 1 a 6 commits,
mesclada no mesmo dia. Por isso a `main` anda rápido, e a nossa branch
precisa acompanhar:

- **antes de começar uma mudança**, trazer a `main` para a branch:
  `git checkout feat/infra-jarvis && git merge origin/main` (se ela estiver só
  atrás, é avanço rápido, sem commit de merge);
- **enquanto a branch tiver algo que a `main` não tem**, um `plan` feito por
  outra pessoa a partir da `main` mostra os nossos recursos novos como sobra
  a destruir. Avisar a Natália quando empurrar algo que não seja só bump de
  imagem.

Em 2026-09-21 a `feat/infra-jarvis` foi avançada até a `main` (que já tinha
os dois merges do dia e o trabalho dela), e a `feat/infra-jarvis-alarmes`
ficou sem uso — já está mesclada.

**Quando a mudança toca o `sales_force_crm`:**

| Mudança | Jarvis | `sales_force_crm` |
|---|---|---|
| Código do app (tela, prompt, regra, consulta de referência) | commit | só para ir ao ar: build e push (passo 8) e **bump da imagem** (passo 9) |
| Migration nova | commit | bump, como acima, e rodar o `migrate` (passo 10) |
| Variável de ambiente nova | commit do código que a lê | commit no `jarvis.tf` (`jarvis_environment`) |
| Secret novo | commit do código que o lê | secret criado **à mão** antes; depois commit no `jarvis.tf` (`jarvis_secrets`) |
| CPU, memória, número de tasks, domínio | — | commit em `variables.tf` |
| Só documentação ou teste | commit | — |

**As regras:**

1. **Só o que é nosso, arquivo por arquivo.** `git add` com o caminho de cada
   arquivo e `git diff --staged` antes do commit. Nunca `git add -A`,
   `git add .` ou `git add infra/` no `sales_force_crm`: outras frentes
   trabalham no mesmo clone, e isso levaria o trabalho delas junto (regra da
   Natália, 2026-09-21).
2. **Um commit por assunto.** "Login por código" e "ajuste do gráfico" são
   dois commits, mesmo feitos no mesmo dia: é o que permite desfazer um sem o
   outro.
3. **Mensagens**, no estilo de cada repositório:
   - Jarvis: uma frase em português dizendo o que muda, como no histórico —
     *"Usa uma chave de cache só no planejamento, que é onde está 90% do custo"*;
   - `sales_force_crm`: `feat(infra): jarvis - …`, `fix(infra): jarvis - …` e,
     para trocar a imagem, exatamente `deploy: bump jarvis_container_image pra <hash>`.
4. **Sem linha `Co-Authored-By`** nos commits.
5. **Commit no Jarvis antes do build.** A tag da imagem é o hash do commit;
   o passo 8 recusa rodar com arquivo fora de commit.
6. **Push do `sales_force_crm` antes de qualquer `apply`** (regra 3), e todo
   `apply` com `-target` nos recursos do Jarvis — o state é compartilhado
   com o Cockpit, e o `plan` sem alvo mostra também o que é das outras
   frentes.
7. **Nunca entram:** `.env`, `terraform.tfstate`, `tfplan*` — já estão no
   `.gitignore` dos dois — nem senha, chave ou código de acesso em mensagem de
   commit.
8. **Nada é commitado nem empurrado sem o ok do Rubens.**

### Onde cada peça mora, e o que copiar

Mesma tabela da seção 0 do passo a passo, com o nome do Jarvis no lugar:

| Peça | Arquivo | Exemplo a copiar |
|---|---|---|
| Role Postgres + Secrets Manager | fora do Terraform | `cockpit-prod-trade-fv-db-*` |
| Security Group | `infra/modules/network/main.tf` | `aws_security_group.trade_fv` |
| Target Group + Certificado + Regra do ALB | `infra/modules/alb/main.tf` | `aws_lb_target_group.trade_fv`, `aws_acm_certificate.trade_fv`, `aws_lb_listener_rule.trade_fv_host` |
| ECR repo | `infra/ecr.tf` | `aws_ecr_repository.trade_fv` |
| Task Definition + Service | `infra/modules/compute/jarvis.tf` (arquivo novo) | `infra/modules/compute/trade_fv.tf` |
| Variáveis raiz | `infra/variables.tf` | blocos `trade_fv_*` |
| Fiação entre módulos | `infra/main.tf` | blocos `trade_fv_*` em `module.network`/`alb`/`compute` |
| Outputs | `infra/outputs.tf` | blocos `trade_fv_*` |

### O que já existe e o que falta

| Peça | Situação |
|---|---|
| VPC, subnets, ALB público + listener HTTPS, cluster ECS, execution role, log group, RDS `cockpit-prod-db` | ✅ compartilhados, é só referenciar |
| Saída para a internet | ✅ resolvida: subnet **pública** com `assign_public_ip = true`, **sem NAT Gateway** — é o que os cinco services já fazem |
| Permissões e state remoto | ✅ `AdministratorAccess` no usuário `rubens` (2026-09-21); state em S3 com lock no DynamoDB |
| Roles e schema no Postgres, secrets | ✅ criados à mão no passo 1 — não são Terraform |
| ECR, security group, target group, certificado, regra de listener, task definition, service | ✅ criados no passo 4 |
| Anexo do certificado ao listener | ✅ passo 6, depois de o certificado ser emitido |
| Redis | ✅ container dentro da própria task, rodando (ver abaixo) |
| DNS no registro.br | ✅ passos 5 e 7, feitos à mão no registro.br |

Custo do que o Jarvis acrescenta: **~US$ 25/mês de AWS** (ECR ~1, Fargate ~18,
Secrets ~4, logs ~2) **+ US$ 10 a 30 de OpenAI**. ALB, ACM, banco e saída para
a internet são US$ 0 — já estão pagos.

### Redis: container, não ElastiCache

Não existe ElastiCache em produção (o módulo `cache/` está no repositório e
nunca foi instanciado). A fila do Celery entra como **terceiro container da
mesma task**: em `network_mode = "awsvpc"` todos os containers da task
compartilham a interface de rede e se enxergam por `127.0.0.1`.

```
task cockpit-prod-jarvis
├── jarvis-web     gunicorn :8000            essential=true   → target group
├── jarvis-worker  celery -P solo            essential=false
└── jarvis-redis   redis:7-alpine 127.0.0.1  essential=true
```

`CELERY_BROKER_URL=redis://127.0.0.1:6379/0`. Custo zero, nenhuma peça nova, e
é o padrão da casa (o `cockpit-worker` já roda como sidecar). **Escala na
horizontal mesmo assim**: a resposta não trafega pela fila — o navegador busca
em `GET /api/conversations/:id/messages/?after=N`, que lê o Postgres. Quem
enfileira e quem consome estão sempre na mesma task, e qualquer task responde
o polling. O que se perde é só isto: um deploy derruba as perguntas em voo (a
pergunta leva ~30 s, o usuário reenvia; é fila, não banco).

---

### O fluxo, na ordem validada ponta a ponta

Os onze passos abaixo são os do "fluxo real de deploy" do
`PASSO_A_PASSO_DEPLOY_TERRAFORM.md`, na mesma ordem e pelo mesmo motivo. O que
é acréscimo do Jarvis (migrations, usuários) está marcado.

#### Passo 0 — Pré-condições da máquina ✅

Conferido em 2026-09-18 e 2026-09-21:

- [x] Túnel SSM aberto (só funciona no WSL): `bash infra/rds/abrir_tunel_wsl.sh`
- [x] `aws sts get-caller-identity` → `arn:aws:iam::595324409476:user/rubens`
- [x] Docker 28.0.4 com daemon de pé; `psql` 17.4; AWS CLI 2.36
- [x] Senhas no `bi/.env` (`COCKPIT_DB_PASS` = `rubens_dba`, `ANALYTICS_DB_PASS`
      = `bi_chatbot_ro`) — lidas só para dentro de variável de shell
- [x] Subdomínio definido: **`jarvis.easelabs.app.br`**
- [x] Terraform **1.16.2** instalado em 2026-09-21
      (`winget install Hashicorp.Terraform` — o id tem `c` minúsculo; com
      `HashiCorp` o winget não acha o pacote). Exige shell novo para o PATH

#### Passo 1 — Role no Postgres e secrets no Secrets Manager ✅

Seção 1 do passo a passo. **Precisa existir antes do primeiro `plan`**: a task
definition usa `data "aws_secretsmanager_secret"`, que só lê secret existente —
sem eles o `plan` falha na resolução do data source.

**✅ Concluído em 2026-09-21.** A DBA executou
`GRANT CREATE ON DATABASE easelabs TO rubens_dba` e daí saiu tudo o que este
passo pedia. Comando rodado:

```bash
# hex: sem caractere que precise de escape em DSN, psql ou JSON
export SENHA_APP=$(openssl rand -hex 24)

psql "host=127.0.0.1 port=15432 dbname=easelabs user=rubens_dba sslmode=require" \
     -v ON_ERROR_STOP=1 -v senha_app="$SENHA_APP" \
     -f infra/app-db/02_criar_schema_jarvis.sql
```

**Uma pedra no caminho, já corrigida no script.** No PostgreSQL 16 quem cria
uma role recebe `ADMIN` sobre ela, mas a associação nasce com `SET` desligado
(`admin_option = t, set_option = f`) — e `CREATE SCHEMA ... AUTHORIZATION`
exige poder **assumir** a role. O script parava em
`must be able to SET ROLE "jarvis_app"`. A correção é uma linha, agora na
seção 1: `GRANT jarvis_app TO CURRENT_USER WITH SET TRUE, INHERIT FALSE`. O
`INHERIT FALSE` é explícito de propósito: sem ele o `GRANT` adota o
`rolinherit` de quem executa, e o `rubens_dba` passaria a carregar os
privilégios da `jarvis_app` em toda conexão — tabela criada à mão no schema
nasceria com o dono errado.

Conferências de saída, todas verdes em 2026-09-21:

| O que | Resultado |
|---|---|
| schema `jarvis` em `easelabs`, dono `jarvis_app` | ✅ |
| `jarvis` é o **único** schema com `pode_criar = t` — os outros 15, inclusive `public`, deram `f` | ✅ |
| `jarvis_app` sem `CREATEDB` e sem `SUPERUSER` | ✅ |
| `rubens_dba` **não** herda a `jarvis_app` (`pg_has_role(...,'USAGE') = f`) | ✅ |

E a prova de fogo, conectando **como a aplicação**, com a senha lida do
Secrets Manager:

| Tentativa | O banco respondeu |
|---|---|
| `search_path` na conexão | `jarvis`, sem ninguém configurar nada |
| `CREATE TABLE` dentro do `jarvis` | funcionou |
| `CREATE TABLE public.…` | `permission denied for schema public` |
| `SELECT … FROM cddd.fato_cdd` | `permission denied for schema cddd` |

As duas últimas linhas são a ADR-0002 em vigor sem database separado: o
`migrate` não tem para onde escapar, e a conexão que escreve não enxerga dado
de negócio.

Em seguida os secrets — campos discretos, nunca DSN como string, mesma
convenção do `cockpit-prod-trade-fv-db-*`. São doze porque o Jarvis tem duas
conexões (a que escreve no schema dele e a que lê o negócio, ADR-0008) mais a
chave da OpenAI e a `SECRET_KEY`:

```bash
export RDS_HOST=cockpit-prod-db.cpuoqq0y8xnn.sa-east-1.rds.amazonaws.com
export SENHA_RO_LEITURA='<senha do bi_chatbot_ro, do bi/.env>'
export CHAVE_OPENAI='sk-...'
export DJANGO_SECRET=$(uv run python -c \
  "from django.core.management.utils import get_random_secret_key as g; print(g())")

cria() { aws secretsmanager create-secret --name "$1" --secret-string "$2" >/dev/null && echo "  ok  $1"; }

cria cockpit-prod-jarvis-db-host     "$RDS_HOST"
cria cockpit-prod-jarvis-db-port     "5432"
cria cockpit-prod-jarvis-db-name     "easelabs"
cria cockpit-prod-jarvis-db-user     "jarvis_app"
cria cockpit-prod-jarvis-db-password "$SENHA_APP"

cria cockpit-prod-jarvis-analytics-db-host     "$RDS_HOST"
cria cockpit-prod-jarvis-analytics-db-port     "5432"
cria cockpit-prod-jarvis-analytics-db-name     "easelabs"
cria cockpit-prod-jarvis-analytics-db-user     "bi_chatbot_ro"
cria cockpit-prod-jarvis-analytics-db-password "$SENHA_RO_LEITURA"

cria cockpit-prod-jarvis-openai-api-key "$CHAVE_OPENAI"
cria cockpit-prod-jarvis-secret-key     "$DJANGO_SECRET"
```

- [x] **Os 12 criados em 2026-09-21**, conferidos com
      `aws secretsmanager list-secrets --filters Key=name,Values=cockpit-prod-jarvis`
- [x] Senha gerada com `openssl rand -hex 24` e gravada no Secrets Manager na
      mesma execução do `psql` — não passou por arquivo, log nem histórico
- [x] Cuidado que evitou lixo: o `.env` tem `ANALYTICS_DB_PORT=15432`, que é a
      porta do **túnel**. Nos segredos entrou `5432` e o endpoint real do RDS
- [x] **`jarvis_ro` descartada em 2026-09-21** — a role e os 2 segredos dela.
      Ninguém pediu leitura direta da auditoria, e `bi_report` mais o Admin já
      respondem uso, custo e lacunas. Recriar são 4 linhas, documentadas no
      cabeçalho do `02_criar_schema_jarvis.sql`. O que **não** se faz é dar
      essa leitura ao `bi_chatbot_ro`: é sob ela que roda o SQL escrito pela
      IA, que passaria a poder consultar as perguntas de todo mundo

**Migrations aplicadas no mesmo dia.** O `infra/README.md` do `sales_force_crm`
põe `manage.py migrate` logo depois do `CREATE SCHEMA`, fora do ECS, como
trabalho de banco — foi assim que o schema `cockpit` nasceu, e estávamos
exatamente nesse ponto.

```bash
export APP_DB_HOST=127.0.0.1 APP_DB_PORT=15432 APP_DB_NAME=easelabs APP_DB_USER=jarvis_app
export APP_DB_PASSWORD="$(aws secretsmanager get-secret-value \
  --secret-id cockpit-prod-jarvis-db-password --query SecretString --output text)"
uv run python app/manage.py migrate --plan     # conferir antes
uv run python app/manage.py migrate --noinput
```

- [x] 18 tabelas no schema `jarvis`, **todas com dono `jarvis_app`**
- [x] Nenhuma tabela nova em nenhum outro schema (conferido em `pg_tables`
      agrupado por schema)

**Passo 1 concluído.** Duas coisas que nasceram depois dele foram para o
passo 10, onde podem ser feitas de verdade: a carga dos usuários
(`sincronizar_usuarios`, que precisa do serviço de pé) e um `migrate` novo
— a tabela `web_codigodeacesso`, do login por código, foi criada depois
deste `migrate` e ainda não existe no RDS.

Além dos 12 segredos do Jarvis, a task usa um 13º que já existia: o
`cockpit-prod-gmail-app-password`, do Cockpit, para enviar o código de
acesso (ADR-0023). Ele não foi criado aqui — é reaproveitado.

#### Passo 2 — Escrever os blocos do Terraform, com **imagem placeholder** ✅

Seções 2 a 8 do passo a passo, nos arquivos da tabela acima. A branch vem
antes de tudo (regra 3) — e **não sai da `main`**, sai de
`feat/permissoes-rubens-deploy`: o `iam_deploy_rubens.tf` só existe naquela
branch e os recursos dele estão valendo na AWS. Ramificar da `main` faria o
`plan` pedir para destruí-los.

```bash
cd /d/Projetos/sales_force_crm
git checkout feat/permissoes-rubens-deploy && git pull
git checkout -b feat/infra-jarvis
```

O que declarar, copiando do `trade_fv`:

- `infra/modules/network/main.tf` — `aws_security_group.jarvis` (ingress só do
  `alb-sg` na 8000) e mais um ingress no `rds-sg` vindo dele; output do id
- `infra/ecr.tf` — `aws_ecr_repository.jarvis` (`cockpit-prod-jarvis`) +
  lifecycle de 10 imagens + output
- `infra/modules/alb/main.tf` — target group (health check `/api/health/`),
  `aws_acm_certificate.jarvis`, `aws_lb_listener_certificate` e
  `aws_lb_listener_rule.jarvis_host` por `host_header`, **prioridade 50**
  (20/30/40 já usadas por eventos/api/trade_fv)
- `infra/modules/compute/jarvis.tf` — `data "aws_secretsmanager_secret"` dos
  doze (o do Gmail do Cockpit já vem declarado em `sync.tf`, no mesmo
  módulo), task definition com os três containers, service com
  `assign_public_ip = true` e `enable_execute_command = true`, **sem
  `ignore_changes`**, mais a `aws_iam_role_policy` dando à execution role
  `secretsmanager:GetSecretValue` nos ARNs do Jarvis — sem ela a task fica
  presa em `ResourceInitializationError` com todo o resto certo
- `infra/variables.tf` — blocos `jarvis_*`
- `infra/main.tf` — fiação nos três módulos
- `infra/outputs.tf` — `jarvis_acm_certificate_arn` e
  `jarvis_acm_domain_validation_options` (o `jarvis_ecr_url` fica no próprio
  `ecr.tf`, como os dos outros repositórios)

**A variável da imagem nasce num placeholder público**, igual manda o
documento:

```hcl
variable "jarvis_container_image" {
  type = string
  # Placeholder público de propósito: o cockpit-prod-jarvis nasce vazio, e
  # apontar para uma tag dele aqui deixaria o service preso tentando puxar
  # imagem inexistente. Trocado pelo hash real no passo 9.
  default = "public.ecr.aws/nginx/nginx:1-alpine-perl"
}
```

Detalhes do `jarvis-redis` que evitam dor: imagem
`public.ecr.aws/docker/library/redis:7-alpine` (não do Docker Hub, que tem
limite de download por IP), `command = ["redis-server", "--bind", "127.0.0.1",
"--save", "", "--maxmemory", "128mb", "--maxmemory-policy", "noeviction"]` e
`essential = true`.

**O que foi escrito (2026-09-21)** — branch `feat/infra-jarvis`:

| Arquivo | O que entrou |
|---|---|
| `modules/network/{main,variables,outputs}.tf` | `aws_security_group.jarvis` + ingress no `rds-sg` + output do id |
| `ecr.tf` | `cockpit-prod-jarvis` com lifecycle de 10 imagens |
| `modules/alb/{main,variables,outputs}.tf` | target group, `aws_acm_certificate`, `aws_lb_listener_certificate` e regra por `host_header` na **prioridade 50** |
| `modules/compute/jarvis.tf` (novo) | task definition com os 3 containers, service, `aws_iam_role_policy` dos secrets e a task role do ECS Exec. Inclui o envio do código de acesso (ADR-0023): `EMAIL_HOST_USER` e `GMAIL_APP_PASSWORD`, com o secret do Cockpit, nos dois containers |
| `modules/compute/variables.tf`, `variables.tf`, `main.tf`, `outputs.tf` | variáveis, fiação e outputs |

`terraform fmt` e `validate` limpos. Somada contra a base, a branch tem **13
arquivos e 588 linhas adicionadas, nenhuma removida**, tudo
`cockpit-prod-jarvis-*`, e `iam_deploy_rubens.tf` idêntico à base.

| Commit | O quê |
|---|---|
| `b9c4bcf` | hashes do provider para Windows no lockfile |
| `4f06f16` | o Jarvis |
| `b3b711d` → `f207297` | duas policies IAM que pedimos para o `plan` funcionar, **revertidas**: a Natália resolveu o acesso de outro jeito (passo 3) |
| `5d0e1bd` | envio do código de acesso pelo Gmail do Cockpit |

#### Passo 3 — `terraform plan` ✅

**Regra para esta branch, da Natália (2026-09-21): separar as nossas
mudanças do resto e subir só as nossas.** Por isso existem dois planos, e
os dois precisam ser lidos:

1. **O completo** (`terraform plan`), para enxergar o drift do state — o que
   a regra 2 manda ler. Ele **nunca** vai para o `apply` desta branch.
2. **O só do Jarvis**, com `-target`, que é o que vai para o `apply`. No
   PowerShell **cada `-target` vai entre aspas**: sem elas o PowerShell parte
   o argumento no ponto e o Terraform responde `Invalid target "module"`
   (aconteceu em 2026-09-21):

```powershell
terraform plan -out=tfplan-jarvis `
  "-target=aws_ecr_repository.jarvis" "-target=aws_ecr_lifecycle_policy.jarvis" `
  "-target=module.network.aws_security_group.jarvis" "-target=module.network.aws_security_group.rds" `
  "-target=module.alb.aws_lb_target_group.jarvis" "-target=module.alb.aws_acm_certificate.jarvis" `
  "-target=module.alb.aws_lb_listener_certificate.jarvis" "-target=module.alb.aws_lb_listener_rule.jarvis_host" `
  "-target=module.compute.aws_ecs_task_definition.jarvis" "-target=module.compute.aws_ecs_service.jarvis" `
  "-target=module.compute.aws_iam_role.task_jarvis" "-target=module.compute.aws_iam_role_policy.task_jarvis_exec" `
  "-target=module.compute.aws_iam_role_policy.execution_jarvis_secrets"
```

**Rodado em 2026-09-21, fechado com certeza.**

O plano completo, **com refresh**, sem nenhum `AccessDenied`, deu `22 to
add, 6 to change, 2 to destroy`. Só 13 itens são nossos; o resto:

| O que o plano completo faria | De quem | Por que não vai junto |
|---|---|---|
| **Destruir `rubens_admin`** (o `AdministratorAccess` do usuário `rubens`) e recriar as 4 policies antigas | Natália | ela aplicou o IAM novo hoje, de um código que ainda não está em nenhuma branch; a nossa base tem o IAM antigo |
| Trocar a tag `purpose` do usuário `rubens` de `admin` para `dev-db-access` | Natália | mesmo motivo |
| Substituir `aws_ecs_task_definition.sync` (`2d00178` → `27443e3`) e repontar 3 schedules e 1 policy | outra frente | bump de imagem pendente, citado no `CLAUDE.md` |

O plano só do Jarvis deu **12 adições, 1 mudança, 0 destruições**. A
mudança é o `rds-sg` ganhando o ingress "Postgres from jarvis", sem perder
nenhum dos quatro que já tinha. O segredo do Gmail está na policy de leitura,
e senha e remetente chegam aos dois containers.

Histórico, para não repetir: na primeira rodada o `plan` morria com 17
`AccessDenied` no refresh — a policy antiga do `rubens` cobria criar e
alterar, mas não reler o state inteiro. Rodar com `-refresh=false` não serve:
desliga a detecção de drift. Resolveu-se com o `AdministratorAccess` dado
pela Natália.

#### Passo 4 — Commit, push e `apply` ✅

Commit e push já feitos (regra 3). O `apply` é **do plano com alvo** gerado
logo antes — nunca um `terraform apply` sem argumento nesta branch, que
destruiria o `AdministratorAccess` do usuário `rubens` e publicaria o bump do
`sync` (ver passos 2 e 3):

```powershell
cd D:\Projetos\sales_force_crm\infra
# 1. gerar de novo o plano com alvo (o comando está no passo 3) e ler:
#    tem de dar 12 adições, 1 mudança, 0 destruições
# 2. aplicar exatamente esse arquivo:
terraform apply tfplan-jarvis
```

Plano gerado há mais tempo é recusado pelo Terraform se o state mudou no
meio — por isso ele se gera de novo imediatamente antes.

O service sobe servindo nginx. **O target vai aparecer `unhealthy` no
`/api/health/` até o passo 9** — é esperado, o nginx não responde esse path.

**Aplicado em 2026-09-21: 11 criados e o `rds-sg` alterado.**

- [x] ECR, security group, target group, regra do listener (prioridade 50),
      certificado, task definition, service, task role e as duas policies
- [x] `rds-sg` com o ingress "Postgres from jarvis"
- [x] O anexo do certificado ao listener (`aws_lb_listener_certificate.jarvis`)
      falhou com `UnsupportedCertificate`, **e é esperado**: o ALB só aceita
      certificado já emitido, e o nosso estava `PENDING_VALIDATION`. É ordem,
      não erro de configuração — **o item foi para o passo 6**
- [x] State consistente depois da falha: o plano com alvo ficou em `1 to add`,
      só o anexo do certificado

**A task subiu**, e isso já valida os segredos: com a policy de leitura
errada ela morreria em `ResourceInitializationError` antes do primeiro
container. `jarvis-web` e `jarvis-redis` rodando; `jarvis-worker` parado com
código 127 ("comando não encontrado") — esperado, o placeholder nginx não tem
`celery`. Como ele não é essencial, a task segue de pé. Resolve sozinho no
passo 9.

#### Passo 5 — CNAME de validação do certificado ✅

```bash
terraform output jarvis_acm_domain_validation_options
```

- [x] Criado no **registro.br** em 2026-09-21, zona `easelabs.app.br`, e
      conferido no DNS do Google e da Cloudflare. Valores tirados do
      certificado:

| Campo | Valor |
|---|---|
| Tipo | `CNAME` |
| Nome | `_a3091bb1e1464f6881c11f71cb86c874.jarvis` |
| Valor | `_7e37ca99644c91a51e24296ad9d15316.wzccmgtwzk.acm-validations.aws.` |

O registro.br completa o domínio sozinho no campo de nome: por isso vai só
`_a3091…jarvis`, sem o `.easelabs.app.br.` do fim.

**O caminho no registro.br:**

1. Entrar em https://registro.br com a conta que administra o
   `easelabs.app.br` — é quem criou os CNAMEs dos certificados do `eventos`,
   da `api` e do `trade-fv`. Se não for você, é essa pessoa que faz os passos
   5 e 7.
2. Na lista de domínios, abrir o **`easelabs.app.br`**.
3. Na seção de **DNS**, abrir a edição da **zona** ("Editar zona" ou
   "Configurar zona DNS", conforme a versão da tela). Se a tela disser que o
   domínio usa **servidores DNS externos**, a zona não fica no registro.br: o
   registro vai no provedor indicado ali, com os mesmos três campos.
4. **Nova entrada** → tipo `CNAME`, nome e valor da tabela acima.
5. **Salvar** (em algumas versões há um segundo "Salvar alterações" para
   publicar a zona). Se o campo de valor recusar o ponto final, tire o ponto.

Para conferir, de qualquer terminal:
`nslookup -type=CNAME _a3091bb1e1464f6881c11f71cb86c874.jarvis.easelabs.app.br`
— tem de responder o valor `…acm-validations.aws`.

#### Passo 6 — Esperar o certificado virar `ISSUED` ✅

```bash
aws acm describe-certificate --region sa-east-1 \
  --certificate-arn arn:aws:acm:sa-east-1:595324409476:certificate/9573c508-ed5a-48ed-a5cc-5d32b428d00e \
  --query 'Certificate.Status'
```

Geralmente minutos; pode levar horas dependendo da propagação. O status muda
sozinho, sem Terraform.

- [x] Certificado `ISSUED` (2026-09-21, minutos depois do CNAME)
- [x] **Anexar o certificado ao listener** — veio do passo 4, que falhou nele
      de propósito: o ALB só aceita certificado já emitido. Um `apply` só dele:

```powershell
cd D:\Projetos\sales_force_crm\infra
terraform plan -out=tfplan-cert "-target=module.alb.aws_lb_listener_certificate.jarvis"
# conferir: 1 to add, 0 to change, 0 to destroy
terraform apply tfplan-cert
```

Sem esse anexo, quem abrir `https://jarvis.easelabs.app.br` recebe o
certificado do Cockpit e um aviso de site inseguro.

Aplicado em 2026-09-21: `1 added, 0 changed, 0 destroyed`, e conferido no
listener HTTPS do ALB.

#### Passo 7 — CNAME final ✅

- [x] No registro.br, mesmo caminho do passo 5: `CNAME`, nome **`jarvis`**,
      valor **`cockpit-prod-alb-1971305495.sa-east-1.elb.amazonaws.com.`**
      (o DNS do ALB, conferido com `terraform output -raw alb_dns_name`)
- [x] Só depois do passo 6: com o CNAME antes do certificado anexado, o
      navegador mostra o aviso de site inseguro

Conferido em 2026-09-21 em 8.8.8.8 e 1.1.1.1: `jarvis.easelabs.app.br` é
CNAME do ALB; HTTPS apresenta o certificado do Jarvis; HTTP responde 301
para HTTPS. O HTTPS devolve 502 até o passo 9 — é o nginx provisório do
passo 4, não problema de DNS. O resolvedor da máquina pode demorar mais a
enxergar o CNAME novo.

#### Passo 8 — Build e push da imagem real ✅

Fora do Terraform, e **neste repositório** — o código do Jarvis está aqui, não
no `sales_force_crm`. Antes do build, os ajustes de código:

- [x] `Dockerfile` no padrão multiestágio do `sales_force_crm/Dockerfile`:
      estágio `builder` com `build-essential`/`libpq-dev`, estágio `runtime` só
      com `libpq5`, usuário `app` sem privilégio, `EXPOSE 8000`, gunicorn no
      `CMD`. Mantém o **uv** no lugar do Poetry porque o lock deste projeto é
      `uv.lock` — a estrutura é idêntica, só muda o instalador; confirmar com a
      Natália se a exigência do Poetry é literal
- [x] Tirar o `migrate` do `CMD` (vira task avulsa no passo 10) e trocar
      `--bind [::]:$PORT` por `--bind 0.0.0.0:8000` (o IPv6 era do Railway)
- [x] `app/config/env.py`: `assert_not_business_database` hoje recusa host
      `*.rds.amazonaws.com` como banco da aplicação, que passa a ser a
      configuração correta. Vira: recusar RDS **sob teste** e exigir
      `search_path=jarvis` nas `OPTIONS` em runtime.
      Achado de 2026-09-21: pelo túnel o host é `127.0.0.1`, então a trava
      **não dispara** — o `migrate` em produção rodou sem ela reclamar. Ela
      protege menos do que o comentário dela promete, e quem de fato barrou
      escrita fora do lugar foi o privilégio de banco. Mais um motivo para a
      reescrita ser por `search_path`, e não por nome de host
- [x] `database_from_env`: acrescentar `"OPTIONS": {"options": "-c search_path=jarvis"}`
      e `CONN_MAX_AGE`
- [x] Reescrever a **ADR-0002** para descrever a garantia nova
- [x] `uv run pytest` verde — 482 testes
- [x] **Achados no caminho** (2026-09-21):
      - health check do ALB bate no IP privado da task, fora do
        `ALLOWED_HOSTS` → 400 e alvo "unhealthy" para sempre. Resolvido com
        `config/middleware.py` (`HealthCheckMiddleware`, primeiro da lista,
        mesmo padrão do Cockpit), com teste
      - `collectstatic` do build quebrava: o Chart.js vendorizado apontava
        para um `chart.umd.js.map` que nunca foi incluído. Referência
        removida, e um teste roda o `collectstatic` com manifest como o build
      - teste do container: health com `Host: 10.0.1.23:8000` → 200, `/`
        com o mesmo host → 400, estáticos → 200, processo como `app`, sem
        `.env` na imagem, `celery` importa
- [x] **Tudo commitado no repositório do Jarvis** (ver "Como commitar daqui
      em diante"). A tag da imagem é o hash do commit: com arquivo alterado
      fora de commit, a imagem leva código que não está em commit nenhum, e
      ninguém consegue saber depois o que foi ao ar. Em 2026-09-21 havia 33
      arquivos pendentes desde `bd9c53d` (cache explícito, revisão da tela,
      login por código, arrastar na lateral)

```bash
cd /d/Projetos/business_brain/bi
test -z "$(git status --porcelain)" || { echo "há arquivo fora de commit"; exit 1; }
export CONTA=595324409476.dkr.ecr.sa-east-1.amazonaws.com
export HASH=$(git rev-parse --short HEAD)

aws ecr get-login-password --region sa-east-1 | docker login --username AWS --password-stdin $CONTA
docker buildx build --platform linux/amd64 --provenance=false --sbom=false   --output type=image,name=$CONTA/cockpit-prod-jarvis:$HASH,oci-mediatypes=false,push=true .
```

**Por que não `docker build` + `docker push`:** o Docker Desktop anexa um
atestado à imagem e sobe um índice com três entradas no ECR — duas sem tag.
A lifecycle policy do repositório guarda as **10 entradas mais recentes,
com ou sem tag**: cada deploy consumiria três vagas, e uma entrada-filha
poderia expirar separada da imagem em uso. Os outros sete repositórios do
cockpit têm um manifesto Docker simples por imagem; o comando acima gera o
mesmo. Aconteceu no primeiro push (2026-09-21); as três entradas órfãs
foram apagadas e a tag refeita.

- [x] Tag é o hash do commit, **nunca `latest`**
- [x] `--platform linux/amd64`: o Fargate do cockpit roda x86. Numa máquina
      ARM (Mac M1/M2) a imagem sairia na arquitetura errada e a task não sobe
- [x] Tamanho: **83 MB comprimidos no ECR** (o `docker images` do Docker
      Desktop mostra ~390 MB, que é a imagem descompactada — a base
      `python:3.12-slim` mais 147 MB de dependências)

Feito em 2026-09-21: commit `2ea453d` empurrado, imagem
`595324409476.dkr.ecr.sa-east-1.amazonaws.com/cockpit-prod-jarvis:2ea453d`,
manifesto Docker v2, linux/amd64, `USER app`, gunicorn no `CMD`. Conferida
baixando de volta do ECR. O Poetry segue em aberto com a Natália (tabela de
pendências): se for exigência literal, troca o instalador e sai uma imagem
nova — nada nos passos seguintes muda.

#### Passo 9 — Bump da imagem: a forma de deploy deste repositório ✅

Editar o `default` de `jarvis_container_image` em `infra/variables.tf` para
`595324409476.dkr.ecr.sa-east-1.amazonaws.com/cockpit-prod-jarvis:<hash>`.
**Não é `.tfvars`, não é console, não é `update-service`** — a convenção do
projeto é essa, e `git log --grep="^deploy:"` mostra o histórico dela.

**Com alvo, como todo `apply` desta branch** — um `terraform apply` sem
argumento aqui destruiria o `AdministratorAccess` do usuário `rubens` e
publicaria o bump do `sync` (passo 3):

```powershell
cd D:\Projetos\sales_force_crm\infra
terraform plan -out=tfplan-bump `
  "-target=module.compute.aws_ecs_task_definition.jarvis" `
  "-target=module.compute.aws_ecs_service.jarvis"
# conferir: 1 to add, 1 to change, 1 to destroy — a task definition é
# substituída por uma revisão nova (o "destroy" é a revisão antiga) e o
# service passa a apontar para ela. Qualquer outra linha: parar.
cd ..
git add infra/variables.tf
git commit -m "deploy: bump jarvis_container_image pra <hash>"
git push
cd infra
terraform apply tfplan-bump
```

O commit e o push vêm **antes** do `apply` (regra 3), e o `git add` é só do
`variables.tf` — nada de `git add infra/` inteiro, que levaria junto o que
outras frentes tiverem alterado.

Feito em 2026-09-21: `plan` com `1 to add, 1 to change, 1 to destroy` (só a
imagem mudou; as linhas `- mountPoints = []` e afins são o Terraform
normalizando o JSON, não mudança real), commit `dcb2789` empurrado na
`feat/infra-jarvis`, `apply` do `tfplan-bump`. A task nova subiu em ~1 min
e ficou `healthy` no ALB; o worker conectou no Redis da própria task;
`https://jarvis.easelabs.app.br` responde 200.

Para acompanhar um deploy sem ficar esperando à toa: `aws ecs
describe-services` (campo `deployments`) e `aws elbv2 describe-target-health`.
O deploy só fica `COMPLETED` quando a task antiga termina de drenar no ALB —
alguns minutos depois da nova já estar respondendo.

Dois tropeços de máquina:
- o `terraform` do winget não está no `PATH` do PowerShell que o Claude
  usa: chamar por
  `$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Hashicorp.Terraform_Microsoft.Winget.Source_8wekyb3d8bbwe\terraform.exe`
- no Git Bash, `aws logs ... --log-group-name /aws/ecs/cockpit-prod` vira
  caminho do Windows; usar `MSYS_NO_PATHCONV=1`. Os logs do Jarvis ficam no
  grupo **`/aws/ecs/cockpit-prod`**, streams `jarvis-web/…`,
  `jarvis-worker/…` e `jarvis-redis/…`

#### Passo 10 — Migrations e usuários (acréscimo do Jarvis) ✅

O demo do documento não tem banco próprio; o Jarvis tem. `migrate` é task
avulsa, não roda no start do container:

A rede é a mesma do service (conferida em 2026-09-21):

```bash
aws ecs run-task --region sa-east-1 \
  --cluster cockpit-prod-cluster \
  --task-definition cockpit-prod-jarvis \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-0310890fc93479098,subnet-023ca2fe27d946623],securityGroups=[sg-0dc95d138628925f1],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"jarvis-web","command":["python","app/manage.py","migrate","--noinput"]}]}'
```

- [x] **Snapshot manual do RDS antes do `migrate`** (regra 7), com o nome
      `cockpit-prod-db-antes-jarvis-migrate-<AAAAMMDD>`, e esperar ficar
      disponível
- [x] **`migrate` — veio do passo 1.** O primeiro `migrate` (2026-09-21, pelo
      túnel) criou 18 tabelas; a 19ª, `web_codigodeacesso`, nasceu depois, com
      o login por código, e ainda não existe no RDS. **Sem ela ninguém entra
      em produção.** Depois, `migrate --check` não deve ter nada pendente
- [x] Conferir no `psql` que nada nasceu fora do schema:
      `SELECT schemaname, count(*) FROM pg_tables GROUP BY 1 ORDER BY 2 DESC;`
      — o `jarvis` deve ter 19 tabelas
- [x] **`sincronizar_usuarios` — veio do passo 1**, mesma receita trocando o
      comando por
      `["python","app/manage.py","sincronizar_usuarios","--arquivo","infra/app-db/usuarios_iniciais.csv"]`.
      Cria os quatro administradores já com e-mail e papel de equipe.
      Não é obrigatório para entrar — qualquer `@easelabs.com.br` se cadastra
      no primeiro acesso —, mas sem ele os quatro entrariam como usuários
      comuns

Não há senha para definir: o acesso é por código no e-mail (ADR-0023).

Feito em 2026-09-21, nesta ordem:

| O que | Resultado |
|---|---|
| Snapshot `cockpit-prod-db-antes-jarvis-migrate-20260921` | `available`, 100% |
| `migrate` (task avulsa, task definition `:2`) | `Applying web.0001_initial... OK`, exit 0 |
| `migrate --check` | nada pendente |
| Tabelas por schema | `jarvis` com **19**; `cockpit` 108, `cddd` 31 e os outros intocados |
| `sincronizar_usuarios` | `4 criado(s), 0 atualizado(s), 0 desativado(s)` — os quatro como `is_staff`, sem senha utilizável |
| Produção | `/` e `/api/health/` em 200, `/admin/login/` redireciona para o login por código, **nenhum 500** no log |

A tabela que faltava, `web_codigodeacesso`, é a 19ª. Sem ela, pedir o código
de acesso dava erro — era o que travava a entrada.

Cuidado ao conferir: `run-task` sobe os três containers e o `jarvis-web` é
essencial, então a task para sozinha quando o comando termina — o
`stoppedReason` é `Essential container in task exited`, com exit code 0.
Isso é sucesso, não falha.

#### Passo 11 — Testar e fechar

- [x] `https://jarvis.easelabs.app.br` abre com cadeado, sem aviso
- [x] Login por código: o e-mail chegou em segundos pelo Gmail do Cockpit e o
      código entrou (Rubens, 2026-09-21)
- [x] Uma pergunta que vá ao banco, com o número conferido
- [x] Uma planilha baixada e um gráfico desenhado
- [x] `bi_report --dias 1` em produção (task avulsa): 1 pergunta, 1 pessoa, 1
      planilha, "respondeu com dado" e número ancorado, 1 consulta sem erro
      nem correção, **21,1 s** até a resposta, **US$ 0,0433** na pergunta
      (25.449 tokens de entrada, 10% servidos pelo cache), nenhuma lacuna de
      catálogo. Os 21,1 s ficam acima da meta de 20 s do SPEC — é uma medida
      só, e a investigação do p95 continua na lista do "Depois do deploy"
- [x] Target do ALB `healthy` no `/api/health/` (2026-09-21)
- [x] Log dos três containers no CloudWatch, e o `jarvis-worker` agora
      **rodando** (no passo 4 ele parava com código 127, por causa do nginx).
      Conferido em 2026-09-21: `celery@ip-10-20-0-98 ready.`, conectado no
      Redis da própria task; nenhum 500 no `jarvis-web`
- [x] **Merge na `main` feito em 2026-09-21**, no padrão dela (commit
      `merge: incorpora feat/infra-jarvis em main`, `951618b`), por pedido
      do Rubens. Só adições: 13 arquivos, 588 linhas, zero remoções — o
      `sync` dela seguiu em `2d00178` e o `iam_deploy_rubens.tf` ficou
      intocado (`git diff` do merge nesse arquivo é vazio). Antes do merge a
      `main` tinha ganhado um commit novo dela (`e6c343e`), que entrou na
      base. Depois do merge, `terraform plan` completo (sem alvo) diz **No
      changes** — a `main` agora bate com o que está no ar, e ninguém mais
      vê um plano propondo destruir o Jarvis.
      - a `feat/permissoes-rubens-deploy` já estava mesclada na `main` (topo
        `01dc9cd`) e já havia sido apagada no GitHub; removi a cópia local e
        limpei as referências
      - a `feat/infra-jarvis` continua no GitHub como histórico do que foi
        aplicado passo a passo

**Produção começa sem histórico** (decidido em 2026-09-21). As 53 conversas
do banco local — 20 do `rubens_filho`, herdadas da conta `demo`, e 33 de
teste (`validacao_sintetica`, `chat_local`, `smoke-fase4`) — ficam só no
Docker local. O `migrate` cria tabela, nunca copia dado: o schema `jarvis`
nasceu vazio de propósito, com apenas os quatro usuários.

**Daí em diante, qualquer mudança de código repete só os passos 8 e 9**
(commit no Jarvis, build e push da imagem, bump no `sales_force_crm`), e o 10
quando houver migration nova.

---

### Depois do deploy

Enxugado em 2026-09-21 a pedido do Rubens: dos oito itens abertos ficaram só
estes dois, e os dois foram feitos no mesmo dia. Saíram da lista, por decisão
dele: metric filter de créditos da OpenAI esgotados, AWS Budgets, créditos
pré-pagos da OpenAI, acompanhamento da regra `tentativa_de_injecao`, política
de retenção do histórico e restrição à rede corporativa.

- [x] **Alarme de 5xx no ALB e de task derrubada pelo health check**
      (2026-09-21). Branch `feat/infra-jarvis-alarmes` no `sales_force_crm`,
      arquivo `infra/modules/alb/jarvis_alarmes.tf`, no mesmo padrão do
      alerta do sync: tópico SNS `cockpit-prod-jarvis-alerts` com assinatura
      por e-mail, mais dois alarmes do CloudWatch. `apply` com alvo nos
      quatro recursos: `4 added, 0 changed, 0 destroyed`. Mesclada na
      `main` no mesmo padrão (`2f03e64`), para que um `plan` a partir dela
      não proponha destruir os alarmes; `plan` completo depois: **No
      changes**. Os dois alarmes ficaram em `OK` avaliando dado real.
      - `cockpit-prod-jarvis-5xx`: `HTTPCode_Target_5XX_Count` do **target**
        (o container, não o ALB), soma em 5 min, limite zero — um único 500
        já avisa, porque em dezenas de perguntas por dia não existe "5xx
        normal"
      - `cockpit-prod-jarvis-sem-host-saudavel`: `HealthyHostCount` abaixo de
        1 por **3 minutos seguidos**. Três períodos de 60 s de propósito: no
        deploy a task nova fica alguns segundos sem passar no health check, e
        alarmar nisso viraria alarme falso a cada bump de imagem.
        `treat_missing_data = breaching`, porque métrica ausente significa
        nenhum target registrado — exatamente o caso a avisar
      - Métrica do próprio ALB, sem custo e sem depender de log da
        aplicação. Container Insights está **desabilitado** no cluster, então
        `RunningTaskCount` não existe; `HealthyHostCount` cobre o sintoma
      - **Pendente do Rubens:** confirmar a assinatura do SNS no e-mail que a
        AWS enviou (`PendingConfirmation` até clicar). Sem isso o alarme
        dispara e não entrega

- [x] **p95 acima da meta: investigado em 2026-09-21** — junta o item que
      estava na Fase 8 ("primeira leitura de 28,2 s, mediana 11,9 s e uma
      pergunta de 102 s"). Decomposto sobre as 73 respostas com tempo medido
      no banco local, cruzando `AICall.latency_ms` por etapa com
      `QueryRun.duration_ms`:

      | Onde vai o tempo | Mediana | p95 | Máximo |
      |---|---|---|---|
      | Chamadas ao modelo | 10,9 s | 43,3 s | 102,1 s |
      | Consulta no banco | 0,3 s | 3,9 s | ~4 s |

      **O banco não é o problema: é o modelo, e é a segunda rodada de
      planejamento.** Por etapa (n, média, máximo): `fix` 7, 24,9 s, 80,5 s ·
      `plan` 71, 8,1 s, 34,1 s · `rewrite` 13, 6,5 s, 10,8 s · `answer` 51,
      5,0 s, 15,9 s. Respostas com 3 ou mais chamadas ao modelo levam 29,3 s
      em média.

      O gargalo tem nome: o caminho em que a IA pede o **documento inteiro**
      (`full_context`, `orchestrator.py`). Separando as chamadas de `fix`
      pela flag `contexto_completo` do `request`: com documento inteiro são 3
      chamadas, média **41,0 s** e ~46 mil tokens de entrada; sem ele, 4
      chamadas, média **12,8 s** e ~18 mil tokens. A suspeita registrada em
      18/09 ("a pergunta que cruza áreas, que leva duas seções e uma segunda
      chamada") estava na direção certa, mas o custo não é a segunda chamada
      em si — é ela carregando o documento todo, que também joga fora o
      prefixo do cache. Esforço também pesa: `medium` (plan e fix) dá média
      de 9,7 s contra 5,4 s do `low` (answer e rewrite).

      **Achado de medição, que vale mais que o número:** `AIReply.latency_ms`
      é a soma das chamadas ao modelo (`orchestrator.py:113`) — não inclui
      banco, fila do Celery nem renderização. O p95 do `bi_report`, que é o
      comparado com a meta de 20 s do SPEC, **subestima** o que a pessoa
      sente. Em produção, a primeira pergunta real (2026-09-21) levou 21,1 s
      por essa mesma conta.

      **Decidido pelo Rubens em 2026-09-21: não mexer.** Limitar o caminho
      do documento inteiro é o que baixaria o tempo, e é justamente o caminho
      que existe para a pergunta que cruza áreas — cortá-lo troca segundos
      por resposta pior, e resposta pior não é negócio. A meta de 20 s do
      SPEC fica como referência, não como razão para piorar a resposta. Duas
      coisas continuam valendo saber:
      - o tempo alto é sempre o modelo, nunca o banco (mediana de 0,3 s):
        se um dia ficar lento, é lá que se olha
      - o p95 do `bi_report` mede só as chamadas ao modelo, então o número
        real sentido pela pessoa é um pouco maior

---

## Fase 10 — Anexos: planilha para preencher e imagem para ler
**Status: ✅ no ar (2026-09-21)** · imagem `c49595b`, task definition
`cockpit-prod-jarvis:3`, junto com a Fase 11

Pedido do Rubens: mandar um xlsx/csv e pedir que o Jarvis preencha com dado
de sell-out, ou um print para ele analisar — **com todos os cuidados para
aumentar o mínimo possível o custo**, e sem guardar o arquivo. Decisão e
números na **ADR-0024**.

### Como ficou

- [x] **O arquivo nunca é guardado.** Bytes no Redis da task (cache do
      Django, banco `/1`), 15 min para a entrada e 30 min para a planilha
      preenchida, descartados depois da resposta — também quando ela falha.
      Upload só em memória (`FILE_UPLOAD_MAX_MEMORY_SIZE`), sem arquivo
      temporário em disco. A conversa guarda tipo, nome e resumo — e, da
      imagem, uma **miniatura** (ver a segunda rodada)
- [x] **Da planilha sobe só a forma**: abas, linhas, colunas com tipo e dois
      exemplos. Teto de 4.000 caracteres; no teste real, 212. O modelo devolve
      quatro nomes de coluna, nunca valores; quem preenche é o `openpyxl` com o
      resultado do banco (ADR-0010 dentro da planilha)
- [x] **Casamento das linhas sem token**: idêntico após normalizar, ou nome
      contido em **uma única** chave do banco. A resposta lista o que casou
      por aproximação e o que ficou em branco, pelo nome
- [x] **Imagem**: validada pelo conteúdo (Pillow), reduzida a 1.280 px, lida
      por **uma** chamada ao `luna` com prompt próprio de ~350 tokens, sem
      catálogo e sem banco. Resposta rotulada como vinda da imagem, decisão
      própria (`image_reading`) na auditoria e no `bi_report`. Instrução
      escrita dentro da imagem é registrada e ignorada (ADR-0021)
- [x] **Limites** em `attachments/limites.py`: 5 MiB, 20 mil linhas, 60
      colunas, 8 linhas de amostra; `.xlsx`/`.xlsm`/`.csv` e PNG/JPEG/WEBP.
      Recusa na subida, antes de qualquer chamada paga
- [x] **Tela**: clipe no compositor, **Ctrl+V de print** direto no campo,
      etiqueta do anexo com linhas/colunas ou dimensões, nome do anexo na
      bolha da pergunta, botão "Baixar planilha preenchida" na resposta (que
      vira "expirada" depois do prazo)
- [x] Suíte: **544 testes** (62 novos). Entre eles, um que falha se o
      conteúdo da planilha subir ao modelo, um que confere o limite de 50 mil
      linhas na consulta do preenchimento e um que confere o descarte dos
      bytes quando a leitura da imagem falha

### Medido com a API real (2026-09-21)

| Caso | Resultado | Custo |
|---|---|---|
| Print de painel 1920×1080 (reduzido a 1280×720) | leu as 4 redes, achou a única queda (Drogasil, 980 → 902) e **não obedeceu** a instrução escrita no print | **US$ 0,00056**, 6,2 s |
| Planilha de 5 redes, coluna de sell-out vazia | 1ª versão: 1 de 5 casou (o banco diz "RAIA DROGASIL", a planilha "Drogasil"). Com o casamento por nome contido: **3 de 5**, com as aproximações e as em branco listadas | **US$ 0,046**, o custo normal de uma pergunta |

As duas que ficaram em branco estavam certas em ficar: "Drogaria São Paulo"
é "DROGARIA DPSP" no banco (sigla, não dá para deduzir sem chutar) e a outra
não existe.

### Segunda rodada — depois do teste do Rubens na tela (2026-09-21)

Ele colou o print de uma planilha vazia pedindo "preencha as informações", e
mandou a mesma planilha em xlsx pedindo "pode preencher o que está faltando"
(representantes × PX Ease, PX Aché, VAR %, unidades de sell-out, market
share). O print foi só lido ("não há números na imagem"); a planilha voltou
com "envie a planilha". As causas, todas lidas no registro das chamadas:

- [x] **Print que precisa do banco vira pedido ao banco.** A leitura agora
      diz quando o pedido só se resolve com dado da empresa. Tabela a
      completar é transcrita (cabeçalhos e nomes), vira planilha **em
      memória** e segue o caminho do preenchimento — números do banco,
      arquivo para baixar. Pedido de conferência ("isso bate com o nosso
      sell-out?") vira pergunta autossuficiente ao planejador. A conversão é
      só em memória: no banco fica a pergunta como foi escrita, com a imagem
- [x] **Várias colunas de uma vez**: uma chave e, para cada coluna vazia, a
      coluna do resultado que a preenche — uma consulta só, com CTEs
- [x] **Seções escolhidas também pelos cabeçalhos da planilha**: "pode
      preencher o que falta" não diz tema; "PX EASE YTD" e "SELL OUT" dizem
- [x] **Com planilha, os três temas vão completos.** O terceiro em resumo
      (era a prescrição, justamente o PX pedido) fez o modelo pedir o
      documento inteiro: 47 mil tokens, US$ 0,125. O tema a mais custa
      centavos de fração
- [x] **A planilha acompanha toda chamada ao planejador** — antes, a do
      documento inteiro saía sem ela e o modelo respondia "não há planilha
      anexada" (US$ 0,097)
- [x] **Planilha pendente**: quando o Jarvis pergunta um detalhe antes de
      preencher ("painel atual ou território?", "VAR % contra o quê?"), a
      planilha espera 30 min e a resposta da pessoa a herda. Só a última
      resposta conta: mudou de assunto, a planilha não reaparece
- [x] **Coluna de texto mostra a amostra inteira no resumo** (8 linhas):
      com dois exemplos, o modelo filtrou por dois dos três representantes
- [x] **Validador recusava `VALUES`** — defeito antigo. O `sqlglot` lê
      `WITH x AS (VALUES ...)` como `SELECT * FROM (VALUES ...)`, e o
      validador tomava esse `*` (que só seleciona literais) por `SELECT *` na
      `audit.rx_cadastro_mais_recente`. A pessoa lia "Não consegui montar uma
      consulta segura (SELECT * não é permitido…)" sem haver `*` nenhum. A
      exceção é estreita: só `VALUES` puro, sem join; `*` na tabela,
      `VALUES` com join e `*` em subconsulta continuam recusados, com teste.
      As três consultas reais recusadas passam agora
- [x] **Correção usa o mesmo contexto do plano corrigido** — defeito antigo:
      plano feito com o documento inteiro era "corrigido" com o recortado, e
      o modelo desistia
- [x] **Banco fora do ar não é erro de consulta** — defeito antigo: com o
      túnel caído no meio, a IA foi chamada para reescrever um SQL certo
      (US$ 0,094). Agora conexão recusada ou perdida vira `QueryUnavailable`:
      sem correção, sem lacuna de catálogo, e aviso sem detalhe técnico
- [x] **Prévia da imagem**, como nas outras IAs: no compositor, a própria
      imagem com o X no canto, sem nome de arquivo; na bolha, a miniatura
      (clicar abre maior). Para ela continuar na conversa depois do F5, fica
      guardada uma **miniatura** — JPEG de até 480 px, poucos KB. Ela é tudo
      o que resta do print; a imagem que foi ao modelo continua descartada
- [x] Suíte: **583 testes**

Medido na planilha real, depois das correções: a primeira pergunta custa
~US$ 0,05 (uma chamada, sem documento inteiro) e volta com a dúvida certa
("painel atual ou território?"). Respondida, a chamada que escreve a consulta
dos cinco indicadores custou **US$ 0,088 e 55 s** — é pesada, e é o preço de
um pedido que à mão seriam cinco perguntas. **O preenchimento de ponta a ponta
dessa planilha não completou no teste local**: a consulta passou no validador
e foi executada, mas o túnel SSM caiu no meio. Fica para a validação do
Rubens.

### Achado no caminho

- [x] **Contagem de reenvio do código mostrava 61 s.** Com os dois pedidos
      no mesmo tique do relógio (o do Windows tem ~15 ms), `int(60,0) + 1`
      dava 61. Trocado por arredondar para cima, com teste que falhava antes.
      Era o teste do login que falhava de vez em quando

### No ar (2026-09-21, junto com a Fase 11)

A pedido do Rubens ("suba, para que já reflita no app"), sem teste a mais na
API. Passos 8, 9 e 10 da Fase 9, com **uma mudança de ordem** para não haver
erro durante a troca — as migrations antes do serviço trocar de imagem (o
código novo precisa das colunas novas; o antigo convive com elas):

| Etapa | Resultado |
|---|---|
| Commits no Jarvis (`main`) e árvore limpa | `c49595b` no GitHub |
| Imagem (`buildx`, sem atestado) | `cockpit-prod-jarvis:c49595b`, manifesto Docker v2, 91 MB |
| Bump na `feat/infra-jarvis` (depois de trazer a `main`) | `d81283a deploy: bump jarvis_container_image pra c49595b`, empurrado antes do `apply` |
| Snapshot do RDS | `cockpit-prod-db-antes-jarvis-anexos-20260921`, `available` |
| `apply` só da task definition | revisão 3 criada; o serviço seguiu na 2 |
| `migrate` (task avulsa, revisão 3) | `ai_orchestrator.0003`, `0004`, `messaging.0003`, `0004` — OK, exit 0 |
| `apply` só do serviço | revisão 2 → 3, rollout `COMPLETED`, alvo `healthy` |
| Conferência | site 200, JavaScript novo servido, `/api/anexos/` responde (403 sem login), worker `ready`, zero 500 no log |

**Tropeço:** o `apply` do serviço foi passado por `Select-Object -First 3` no
PowerShell, que encerra o pipeline e matou o Terraform depois de mudar a AWS
— o lock do state (compartilhado com a Natália) ficou preso. Conferido que o
lock era desta máquina e deste apply, e que o state já tinha a revisão 3; só
então `force-unlock`. `plan` depois: **No changes**. Regra para o futuro:
nunca cortar a saída de um `apply`; filtrar com `Select-String` sem `-First`.

- [ ] Validação do Rubens na tela, em produção: print colado, planilha,
      pergunta de porquê

---

## Fase 11 — Investigação de perguntas de porquê, e resposta em blocos
**Status: ✅ no ar (2026-09-21)** · junto com a Fase 10, imagem `c49595b`
(ver "No ar" na Fase 10)

Pedido do Rubens: "Porque a Ease Labs caiu em Sell Out em jul/26?" voltou em
produção como tabela crua. O Jarvis tem de **investigar** — geral ou
concentrada num GR; se geral, concorrente roubou share; se concentrada, setor
vago ou performance; se performance, prescrição do painel e concorrente na
prescrição — e responder com um racional, não com uma consulta. E a resposta
não precisa ser sempre texto + tabela + gráfico. Decisão na **ADR-0025**.

### O que o registro de produção mostrou

- [x] **A análise existia e foi jogada fora.** Os dois rascunhos diziam, com
      razão, que o sell-out não caiu (subiu 6,7%, puxado pelo CDD). A
      checagem de números reprovou os dois porque o texto dizia "61" onde o
      banco tinha -61: a expressão que acha número no texto ignora o sinal.
      Corrigido — o valor sem sinal passa, número inventado continua
      reprovado. Os dois rascunhos reais passam agora
- [x] A conversa estava em **produção, conversa 4** ("Porque a Ease Labs caiu
      em Sell Out em jul/26?"), não na de título "Quantas unidades a Ease
      vendeu no total, mês a mês, em 2026?" — essa só tem a primeira pergunta

### Como ficou

- [x] **Investigação em rodadas** (`investigate` → hipóteses com consulta →
      achados → aprofunda ou `conclude` → análise). Roteiro no `planner_v2`,
      seção 13; como contar a investigação no `answerer_v2`, seção 8
- [x] **Tetos:** 3 chamadas ao planejador, 4 consultas por rodada; consulta
      que falha vai nos achados, sem correção própria
- [x] **Pergunta de porquê leva sell-out, força de vendas e prescrição
      completos** desde a primeira rodada — sem isso, o modelo pede o
      documento inteiro
- [x] **Resposta em blocos** (texto, tabela, texto, gráfico) na investigação e
      na pergunta comum; tabela e gráfico desenhados pela tela com os números
      do banco. Bloco que aponta dado inexistente cai
- [x] **`ROUND(x, n)`** convertido para `numeric` pelo validador — derrubou a
      rodada 1 inteira do primeiro teste. As 4 consultas reais que tinham
      falhado por isso rodam agora
- [x] **Tabela crua sem ruído** (`-234,88`, não `-234.87999999999982`) e **sem o
      rótulo "Resultado da consulta"**
- [x] **Progresso na espera** ("Testando: a queda foi concentrada?"), e o
      painel "Ver fonte" lista todas as consultas da investigação
- [x] Suíte: **616 testes**

### Medido (modelos reais, banco de produção pelo túnel)

| Pergunta | Rodadas / consultas | O que respondeu | Custo |
|---|---|---|---|
| Porque a Ease Labs caiu em Sell Out em jul/26? | 2 / 4 | "Não caiu: +6,7% contra junho e +5,4% contra jul/25"; por GR, só SEM REP recuou | US$ 0,19, 41 s |
| Por que o sell out da Ease Labs caiu em junho de 2026? | 2 / 5 | CDD −679; queda disseminada nos 3 GRs; o mercado **cresceu** 2,2% e o share caiu de 8,53% para 7,52% — perda de participação | US$ 0,18, 52 s |

Pergunta de porquê custa ~US$ 0,18 a 0,30, contra ~US$ 0,04 de uma pergunta
de número.

### Perguntas tricky (2026-09-21)

O Rubens testou em produção as perguntas de `chatbot_perguntas_teste.md`
(conversa "perguntas tricky - testes", US$ 0,16 no total) e a maioria falhou.
Pedido: deixar os casos claros no prompt, **de maneira generalista**, e
**não gastar com novos testes na API**. E o roteiro de investigação não é
receita: é exemplo de raciocínio.

- [x] **Roteiro vira exemplo** (`planner_v2`, seção 13, "Pense, não siga
      receita"): cada porquê pede pensar no que pode ter causado aquilo,
      naquele contexto, juntando ou não as áreas
- [x] **Seção 7.1 do `planner_v2`, "a pergunta cabe nos dados?"** — princípios,
      não respostas decoradas: o grão de cada fonte (prescrição é mensal e só
      Extrato × Canabidiol; extras/MP/SS não existem por PDV; concorrente só
      no TD por brick), dado que não existe não é zero (meta, próxima visita,
      estoque fora das redes), foto não é "hoje" (data da carga por rede),
      período conta do fim da base, uma medida oficial e dita, duas leituras
      oficiais → perguntar (painel × território, Mercado × Ease, varejo ×
      público, ruptura por SKU sem somar), mês sem ano = o mais recente,
      contagem distinta, SEM CAT, resposta curta completa a pergunta anterior
- [x] **Redação** (`answerer_v2`): acima de dez linhas a tabela é sempre bloco,
      nunca linhas escritas; cita a data da foto, a medida usada e o corte
      da base
- [x] **Três falhas que eram do sistema**, lidas no registro de produção:
      - "Quais CDs estão em ruptura?" → "problema técnico" duas vezes: a
        redação escrevia 50 linhas, estourava o limite e o JSON vinha cortado
        — e o sistema **repetia a chamada três vezes**. Agora saída cortada é
        `AIOutputTruncated`, não é repetida e cai para a tabela
      - "2026" em resposta a "De qual ano é agosto?" → "não entendi a
        pergunta". Agora resposta curta a um pedido de detalhe vai ao
        planejador
      - estoque da Raia virou tabela crua porque o texto citou "30" (de
        "Isolado 30 mL", nome da coluna) e "21" (a data de hoje). A checagem
        aceita a data de hoje e dose/volume no nome da coluna (só com a
        unidade colada: `total_4500` continua sem valer)
- [x] Suíte: **624 testes**. Nenhum teste novo na API
- Custo: o `planner_v2` ficou ~1.100 tokens maior; como vai no prefixo com
  cache, são frações de centavo por pergunta

### No ar

- [x] Publicado com a Fase 10 (imagem `c49595b`, migration
      `ai_orchestrator.0004_rodada_de_investigacao` aplicada)
- [ ] Validação do Rubens na tela, em produção

---

## Fase 12 — Lista longa, projeções e custo
**Status: ⏳ implementado e testado localmente; falta ir ao ar (2026-09-22)**

### Lista longa, agora de forma generalista

O "problema técnico" da ruptura foi corrigido caso a caso na Fase 11 (saída
cortada não é repetida e cai para a tabela). O Rubens pediu a correção da
**causa**, para qualquer pergunta:

- [x] **Resultado com mais de 10 linhas: o modelo não escreve a lista.** Ele
      recebe uma amostra de 12 linhas, escreve o texto e aponta a tabela; a
      tela desenha a lista inteira com os dados do banco
      (`MAX_LINHAS_NO_TEXTO`, `AMOSTRA_DA_LISTA_LONGA`)
- [x] **Se o modelo não apontar a tabela, o sistema a acrescenta**: a pessoa
      nunca fica com um texto falando de uma lista que não está na tela
- [x] Economiza nos dois lados: menos linhas na entrada e uma resposta que
      não gasta a saída inteira transcrevendo o que já está no banco

### Projeções (mudança no documento de referência)

- [x] O documento deixava toda projeção para o app de Forecast de Reposição.
      Agora **a IA projeta** sell-out, prescrição, PBM e outras séries: método
      simples e defensável (tendência, média móvel, mesmo período do ano
      anterior), **calculado na consulta**, com o histórico no resultado e o
      método dito na resposta
- [x] **Só em projeção de Sell Out ou Sell In da Ease** entra a orientação de
      conferir o **dashboard de Forecast de Reposição**. Ela é acrescentada
      pelo sistema (`canned.RESSALVA_DE_FORECAST`), a partir de uma marca do
      planejador — não depende de o modelo lembrar e não custa token. Em
      projeção de PX ou PBM, nada é dito sobre o dashboard
- [x] A ruptura de hoje continua sendo `dia = 0`; os outros dias da projeção
      de reposição podem ser usados quando a pergunta for de projeção

### Custo: onde o dinheiro está (medido em 2026-09-22)

US$ 6,36 gastos na OpenAI até aqui. O que está registrado no banco:

| | Produção | Testes locais |
|---|---|---|
| Respostas | 16 · US$ 0,54 | 87 · US$ 4,51 |
| Planejamento (Terra) | 80% do gasto | 70% (+23% em correções) |
| Redação (Luna) | US$ 0,015 | US$ 0,056 |
| Pergunta comum | US$ 0,03 | US$ 0,045 |
| Investigação | US$ 0,14 | US$ 0,19 |
| Entrada do Terra vinda do cache | 34,8% | 16,3% |

A diferença para os US$ 6,36 são as chamadas diretas dos testes de
capacidade (imagem, medição de tokens), que não passam pelo orquestrador.

**O gasto é uma coisa só: o contexto da chamada que escreve SQL.** A redação
é irrelevante (US$ 0,07 em tudo). Trocar de modelo não é o caminho: o Terra
está onde o erro é caro e invisível, e o Luna já custa um décimo.

- [x] **Uma chamada a menos por investigação**: o planejador marca
      `rodada_final` quando as consultas da rodada já bastam, e o sistema vai
      direto para a análise. Antes, quase toda investigação gastava uma
      chamada só para ele dizer "pode concluir" (~US$ 0,05)

**O que a investigação passa a custar**: a 1ª chamada grava o tema
(~US$ 0,054) e as seguintes leem do cache (~US$ 0,007 cada), porque numa
investigação o tema é sempre o mesmo. Com `rodada_final` poupando uma
chamada, uma pergunta de porquê deve sair por **~US$ 0,07** em vez dos
US$ 0,18 medidos ontem, e a pergunta comum por **~US$ 0,01** depois da
primeira do tema.
- [x] **Cache do contexto por tema.** Havia um ponto de cache só, no prefixo
      fixo; as seções do tema e o schema pagavam entrada cheia em toda
      pergunta (35% de cache, medido). Agora são **dois pontos**: fixo e tema.
      **Medido com a API real em 2026-09-22** (custo do teste: US$ 0,11):

      | Chamada | Entrada | Do cache | Custo |
      |---|---|---|---|
      | 1ª pergunta do tema `sell_out` | 20.298 | 0 (grava 20.262) | US$ 0,0536 |
      | 2ª pergunta, tema diferente (`sell_out` + `estoque`) | 27.396 | 9.929 (36%, só o fixo) | US$ 0,0522 |
      | 2ª pergunta, **mesmo tema** | 20.298 | **20.262 (100%)** | **US$ 0,0071** |

      Ou seja: repetir o tema custa **87% menos**. A API aceita os dois
      breakpoints. O documento inteiro (2ª tentativa) continua sem gravar
      nada — ele nunca é reaproveitado e só pagaria o ágio.
- [ ] Ir ao ar junto com o resto da Fase 12

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
