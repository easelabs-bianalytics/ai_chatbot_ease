# ADR-0022: resolução de nomes e verificação do resultado vazio

## Status
Aceito — 2026-09-18.

## Contexto
Pergunta real: *"compare o sell out do Ricardo Reis e do Hermes Bizotto,
market share, unidades, Varejo, ago/26"*. A IA escreveu
`desc_territorio ILIKE '%HERMES BIZOTTO%' OR ILIKE '%RICARDO REIS%'`, não
achou nenhum dos dois e respondeu *"a consulta rodou e não retornou nenhuma
linha"*.

Três erros encadeados, todos generalizáveis:

1. **Buscou pelo nome completo.** O cadastro grava `HERMES BIZZOTO` em
   `cddd.forca_vendas` e `Hermes Bizzotto` em `cddd.dim_ct` — grafias
   diferentes na mesma casa, e nenhuma igual à que o usuário digitou.
2. **Perdeu quem não casou.** Com os dois nomes no mesmo `WHERE`, quem não
   resolve simplesmente some do resultado; não há como a resposta dizer o
   que houve com ele.
3. **Tratou "zero linhas" como "não houve".** Ricardo Reis foi desligado em
   18/05/2026: ele não está na `cddd.forca_vendas`, que é a foto de hoje. A
   resposta certa não é um aviso vazio, é *"ele saiu em maio/26"*.

A regra "representante pelo nome usa `ILIKE '%primeiro nome%'`" já existia no
documento — dentro da seção 5, Força de Vendas. A pergunta era de sell-out,
então o contexto foi recortado na seção 2 (ADR-0015) e a regra nunca chegou
ao modelo. Regra que vale para tudo não pode morar em uma seção.

## Decisão

1. **Duas regras no preâmbulo do documento e no núcleo do contexto** — o
   núcleo vai em toda pergunta, independente do tema:
   - *Resolva o nome antes de medir*: nome próprio entra por pedaço (só o
     primeiro nome, ou só o sobrenome) com `ILIKE`, nunca inteiro; se o
     pedaço trouxer mais de um, mostre os encontrados e pergunte.
   - *Nenhuma linha não é zero*: antes de concluir que não houve, verifique
     se o nome existe, se a pessoa estava ativa no período e se o período
     tem carga; a resposta diz o que aconteceu.
2. **Comparação entre nomes resolve primeiro e mede depois**: uma CTE
   `pedidos(pedaco) AS (VALUES ...)` com `LEFT JOIN` no cadastro e no fato,
   para que todo nome pedido apareça no resultado mesmo sem venda. Fica no
   núcleo como esqueleto e no documento como consulta de referência E27,
   com o caso de validação correspondente. A `cddd.dim_ct` entra junto,
   porque é a `data_demissao` que explica a ausência — e essa coluna passou
   a aparecer também na lista de tabelas da seção de sell-out, senão o
   modelo não sabe que ela existe quando o tema não é força de vendas.
3. **Verificação do resultado vazio, no orquestrador**: quando a consulta
   roda sem erro e volta sem linhas, o sistema faz *uma* segunda rodada —
   plano de verificação (seção 9.1 do prompt), validador, execução — e
   entrega o diagnóstico à redação, que explica. Sem diagnóstico, volta o
   aviso curto de antes. A verificação não vira gráfico: o resultado é
   cadastral.

## Consequências
- Custo: uma chamada de plano a mais **só quando a consulta volta vazia**,
  que é raro. Nos testes ao vivo, a pergunta que antes custava US$ 0,06 e
  devolvia um aviso inútil passou a custar cerca de US$ 0,09 e devolver o
  motivo.
- Medido em 2026-09-18, a mesma pergunta passou a responder: *"Hermes
  Bizzotto: 458 unidades, market share 20,79%, Varejo, ago/2026. Não
  consegui comparar Ricardo Reis: a busca por 'Reis' encontrou Marcos Reis e
  Ricardo Reis no cadastro, mas nenhum na força de vendas; o cadastro indica
  desligamento em 18/05/2026. Você quer confirmar qual?"*
- A regra do `LEFT JOIN` cobra atenção: filtro de período ou de canal
  colocado no `ON` não filtra nada, só deixa a coluna nula e a linha continua
  na soma. O documento e o núcleo dizem isso explicitamente, porque a
  primeira versão da própria E27 tinha esse erro.
- `EMPTY_RESULT` continua sendo a decisão registrada, e a tela segue
  mostrando "Sem resultado" — o que mudou é que agora vem acompanhado da
  explicação.
