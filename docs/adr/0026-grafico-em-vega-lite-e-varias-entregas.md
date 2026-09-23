# ADR-0026: Qualquer gráfico em Vega-Lite, e várias entregas numa resposta

## Status
Aceito — 2026-09-23.

## Contexto
O Paulo pediu, em produção, "um gráfico de dispersão mostrando a evolução
prescritiva e o ranking das especialidades que mais prescreveram". Voltaram
uma linha no lugar da dispersão e uma tabela só, com as duas coisas
misturadas por `UNION ALL`, meio vazia de cada lado. Dias antes, "empilhe por
especialidade" também não tinha saído. O Rubens: "ele tem que saber plotar,
não importa o tipo".

Duas limitações de arquitetura explicavam isso:

1. **O vocabulário de gráfico era uma lista de tipos** (linha, barras,
   horizontal; depois área, pizza, empilhado). Cada pedido novo — dispersão,
   bolhas, mapa de calor, barras com linha — exigia código novo na tela. A
   lista nunca acaba.
2. **Uma consulta por resposta.** Pedido com duas entregas diferentes
   (evolução **e** ranking) cabia numa consulta só, e a IA, seguindo a regra
   das "duas visões", juntou-as com `UNION ALL`.

Deixar a IA gerar HTML ou código de gráfico resolveria o vocabulário e abriria
duas portas: script na tela a partir de texto que vem do banco (nome de PDV,
observação de cadastro), e número escrito pela IA no lugar do número do banco
(ADR-0010, ADR-0020).

## Decisão

### Gráfico: especificação Vega-Lite, dado do banco
O Vega-Lite é uma gramática declarativa de gráficos em JSON; descreve
praticamente qualquer gráfico, e os modelos a escrevem bem. A redação passa a
poder preencher `grafico.vega_lite` com uma especificação **sem dados**.

- O servidor (`ai_orchestrator/vega.py`) valida e limpa a especificação: tira
  `data`, `datasets`, `url`, `href`, `usermeta`; recusa marca `image` e texto
  com `://` ou `javascript:`; recusa campo que não existe no resultado nem é
  criado pela própria especificação; apaga título com número sem fonte.
- A tela injeta o resultado da consulta como `data.values`, com o tema do app
  e o formato brasileiro de número e data. As expressões rodam no
  interpretador do Vega (`vega-interpreter`), que não executa JavaScript, e o
  carregador recusa qualquer endereço.
- As bibliotecas (vega 6.4.0, vega-lite 6.4.3, vega-embed 7.3.0,
  vega-interpreter 2.3.2, BSD-3) são servidas pelo próprio app, como o
  Chart.js: ~840 KB, carregados só quando aparece o primeiro gráfico Vega.
- O formato simples (tipo, x, séries, grupo, empilhado) continua valendo e é
  desenhado pelo Chart.js: é mais barato de escrever e cobre o caso comum.

### Resposta: várias consultas quando o pedido tem várias entregas
O plano ganha `consultas` (título, SQL, referência). Pedido com entregas
diferentes — evolução e ranking, vendas e estoque — vira uma consulta por
entrega, cada uma validada e executada, e a redação monta blocos apontando
para cada uma, pelo mesmo caminho da investigação (ADR-0025). "Duas visões"
continua sendo uma consulta: é a mesma medida em dois recortes (canal, painel ×
território).

O ponto B foi implementado em 2026-09-23 (ADR-0027, item 4): campo
`consultas` no plano e caminho `_entregar_varias` no orquestrador.

## Consequências
- Qualquer gráfico que a gramática descreve sai sem código novo na tela.
- O número do gráfico continua sendo o do banco: a IA só escreve o desenho.
- Especificação inválida cai para o formato simples, ou para nenhum gráfico —
  nunca para um gráfico errado.
- Resposta com várias consultas custa uma consulta a mais por entrega; a
  redação é uma só, no modelo barato. A planilha de download fica desligada
  nesse caso, como na investigação, porque sairia de uma consulta só.
