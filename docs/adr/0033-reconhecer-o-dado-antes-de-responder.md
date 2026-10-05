# ADR-0033 — Pergunta sem referência: reconhecer o dado antes de responder

## Status
Aceito em 2026-10-05.

## Contexto
O Jarvis responde bem o que as consultas de referência cobrem: ele parte da
mais parecida e muda período, filtro ou agrupamento (ADR-0014). Sem referência,
ele escrevia a consulta final às cegas, só com o schema e o documento.

A conversa 70 (Amanda, 2026-10-05) mostrou o custo disso: "as planilhas de
adesão e transação do PBM de setembro e outubro, com uma coluna dizendo quem
aderiu e concluiu a transação e quem não". A resposta:
- contou **adesões**, quando a pergunta era sobre **pacientes**;
- disse "500 adesões", que era o limite de linhas da tela (eram 2.796);
- não viu que **outubro não tinha entrado** na base;
- não disse o critério de "concluiu", que mudava o número em 45 adesões;
- procurava a transação adesão por adesão, e o Excel passou de 60 s.

O que resolveu foi o método de quem analisa uma base que não conhece. Antes
de escrever a consulta, foram consultas pequenas:
1. **frescor**: até quando vai cada tabela — 29/09, sem outubro;
2. **grão e chave**: 2.796 adesões de 2.790 pacientes, ligados por
   `ID_CONSUMIDOR` (`bigint` na adesão, texto na transação);
3. **valores**: os status (`CONFIRMADA`, `PRE`, `PEN`, `ANU`) e a data-sentinela;
4. **ambiguidade**: quantos casos caem em cada leitura — 43 pacientes
   compraram outra apresentação, não a da adesão.

Só depois veio a consulta final, no grão pedido, dizendo o critério e até
quando vai o dado.

## Decisão
O Jarvis ganha o modo **reconhecer** (`intent: "explore"`), com esse método
escrito no prompt do planejador (seção 1.1).

- **Quando:** nenhuma referência resolve a pergunta, ou partir da mais
  próxima obriga a mudar o grão, a ligação entre tabelas ou a definição. Não
  vale quando uma referência responde mudando só período ou filtro, nem em
  conversa, esclarecimento ou pergunta de porquê (ADR-0025).
- **Como:** o planejador devolve de 2 a 4 consultas de reconhecimento —
  frescor, grão e chave, valores e ambiguidade —, pequenas, agregadas e
  filtradas pelo período. O orquestrador as roda (`_reconhecer`) e devolve o
  que elas mostraram num bloco "# Reconhecimento". O planejador escreve então
  a consulta final (`answer_with_data`) e as `premissas`: o critério adotado,
  até quando vai o dado e as ambiguidades, com os números. Pode também
  devolver `clarify`, com os números de cada leitura, quando elas levam a
  respostas muito diferentes.
- **A resposta diz as premissas** em uma ou duas frases, logo no começo.
- **Uma rodada só.** Um segundo `explore` vira "não sei", sem terceira
  chamada paga. A chamada depois do reconhecimento passa pelo teto por
  pergunta, porque sem ela nada responde.
- **Aprendizado:** o comando `referencias_do_uso` lista as perguntas que
  passaram pelo reconhecimento, foram respondidas e não levaram 👎, no
  formato das referências. O time de BI revisa e cola no documento, e a
  próxima pergunta parecida sai direto, sem o reconhecimento.
- A consulta do reconhecimento usa o mesmo validador, o mesmo usuário de
  leitura e o mesmo limite de tempo de toda consulta.
- A etapa nova da auditoria é `explore` ("Consulta depois do
  reconhecimento"). A migração só registra a opção; não muda o banco.

## Consequências
- Pergunta sem referência custa uma chamada a mais ao planejador e até
  quatro consultas pequenas: de ~US$ 0,04 para ~US$ 0,08 a 0,12. Pergunta
  com referência, que é a maioria, não muda.
- A resposta sem referência demora mais, de 10 a 20 s, porque as consultas
  de reconhecimento rodam antes.
- O número sai no grão pedido, com o critério e o frescor ditos. Quem lê
  sabe o que o número significa e de quando ele é.
- O documento de referência cresce com o uso, a partir do que o Jarvis
  aprendeu a responder.

## O que foi considerado e ficou de fora
- **Reconhecer em toda pergunta:** dobraria o custo de tudo para ajudar só
  o que não tem referência.
- **Várias rodadas de reconhecimento:** o caso de origem foi resolvido com
  uma; o teto do custo é o que mantém a pergunta abaixo de US$ 0,15.
- **Gravar a consulta nova no documento sozinho:** o documento é do time de
  BI (ADR-0006). O Jarvis propõe, alguém aprova.
