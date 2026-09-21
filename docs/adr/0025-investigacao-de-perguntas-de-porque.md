# ADR-0025: Investigação de perguntas de porquê, e resposta em blocos

## Status
Aceito — 2026-09-21.

## Contexto
"Porque a Ease Labs caiu em Sell Out em jul/26?" voltou em produção como uma
tabela crua, com o rótulo "Resultado da consulta". O Rubens pediu que o
Jarvis **investigue**: a queda foi geral ou concentrada num GR? Se geral,
algum laboratório roubou share? Se concentrada, foram setores sem
representante ou representantes que perderam performance? Se performance, os
médicos do painel prescreveram menos Ease, ou um concorrente ganhou a
prescrição? E que a resposta não seja sempre "texto + tabela + gráfico", mas
texto, tabela, texto, gráfico — quando isso lê melhor.

Lendo o registro da pergunta de produção, duas coisas apareceram:

1. **A análise tinha sido escrita e foi jogada fora.** Os dois rascunhos
   diziam, corretamente, que o sell-out não caiu — subiu 6,7%, puxado pelo
   CDD. A checagem de números (ADR-0010) reprovou os dois porque o texto
   citava "61" e "13,4" onde o banco tinha -61 e -13,4: a expressão que acha
   números no texto não captura o sinal. A tabela crua foi a rede de
   segurança disparando por engano.
2. **O pipeline só sabia fazer uma consulta por pergunta.** Mesmo com a
   checagem certa, uma pergunta de porquê receberia o tamanho da queda, não
   a explicação.

## Decisão

### Checagem de números aceita o valor sem sinal
O conjunto de números sustentados pelo resultado passa a incluir o valor
absoluto de cada um. "Caiu 61 unidades" é o -61 do banco dito com palavra.
Não abre brecha: 62 continua reprovado. Os dois rascunhos reais passam.

### Investigação em rodadas
Nova intenção do planejador, `investigate`, para perguntas que pedem causa
(`context.e_pergunta_de_porque`). Em vez de um SQL, o planejador devolve de
2 a 4 **hipóteses**, cada uma com a consulta que a testa. O orquestrador
executa todas e devolve ao planejador os **achados** (hipótese, colunas e até
30 linhas de cada consulta). O planejador lê e decide: aprofunda o ramo que os
achados apontaram (`investigate`, 1 a 3 consultas novas) ou conclui
(`conclude`). A redação recebe todas as consultas e escreve a análise.

O roteiro — premissa (mês anterior **e** ano anterior) → geral ou concentrada
(GR, território) → mercado e concorrente, ou setor vago e performance →
prescrição do painel e share de prescrição → produtos — está no prompt do
planejador (`planner_v2`, seção 13). A redação (`answerer_v2`, seção 8) conta
a investigação: conclusão primeiro, cadeia de evidências, hipóteses
descartadas, o que os dados não mostram. Relação que os dados mostram pode ser
afirmada; causa continua sendo hipótese quando o dado é só coincidência.

**Tetos, que são o que segura o custo** (`context.py`):
- no máximo **3 chamadas ao planejador** (a primeira e duas de
  aprofundamento);
- no máximo **4 consultas por rodada**;
- consulta que falha **não ganha correção própria**: o erro vai nos achados,
  e o planejador reescreve na rodada seguinte se ela importar.

Pergunta de porquê leva os três temas do roteiro completos (sell-out, força
de vendas, prescrição) desde a primeira rodada: faltar um levaria o modelo a
pedir o documento inteiro, que é a chamada mais cara do sistema.

### Resposta em blocos
A redação pode devolver `blocos`: `texto` (Markdown curto, sem tabela),
`tabela` (índice da consulta e colunas) e `grafico` (índice e sugestão). A
tela desenha tabela e gráfico com os números do banco, formatados. O modelo
nunca escreve os números da tabela — antes ele escrevia a tabela em Markdown,
e foi o arredondamento dele que disparou a reprovação. Bloco que aponta
consulta ou coluna que não existe cai; blocos sem nenhum texto são
descartados e a resposta volta ao formato antigo. Vale também para a
pergunta comum, quando o modelo julgar que texto–tabela–texto lê melhor.

### Correções que o teste real pediu
- **`ROUND(x, n)` com double precision** não existe no Postgres, e o modelo
  escreve assim com frequência: derrubou a rodada 1 inteira do primeiro
  teste. O validador de SQL agora converte o primeiro argumento para
  `numeric`, textualmente, sem mexer no resto da consulta — zero token.
- **Tabela crua sem ruído:** `-234.87999999999982` vira `-234,88`.
- **Sem o rótulo "Resultado da consulta"** na tela.
- **Progresso:** a investigação leva de 40 s a 2 min; a pergunta pendente
  mostra em que hipótese o Jarvis está ("Testando: a queda foi
  concentrada?"), via cache, sem coluna nova.

## Medido (2026-09-21, modelos reais, banco de produção pelo túnel)

| Pergunta | Rodadas / consultas | Resultado | Custo |
|---|---|---|---|
| Porque a Ease Labs caiu em Sell Out em jul/26? | 2 / 4 (2 falharam no ROUND, antes da correção) | "Não caiu: +6,7% contra junho e +5,4% contra jul/25"; por GR, só "SEM REP" recuou | US$ 0,19, 41 s |
| Por que o sell out da Ease Labs caiu em junho de 2026? | 2 / 5 | CDD −679; queda disseminada nos 3 GRs; o **mercado cresceu 2,2%** e o share da Ease caiu de 8,53% para 7,52% — perda de participação, não sazonalidade | US$ 0,18, 52 s |

## Consequências
- Pergunta de porquê custa **~US$ 0,18 a 0,30** e leva **40 s a 2 min**,
  contra ~US$ 0,04 e ~20 s de uma pergunta de número. Com 5 perguntas de
  porquê por dia, ~US$ 30/mês a mais.
- O painel "Ver fonte" de uma investigação lista todas as consultas, cada uma
  com a hipótese que testou. A planilha de download não é oferecida: sairia
  de uma consulta só, escolhida ao acaso.
- A qualidade da investigação depende das consultas de referência cobrirem
  os ramos do roteiro. Onde elas faltam, o modelo escreve SQL do zero — e a
  checagem de números continua sendo a garantia de que ele não inventa.
