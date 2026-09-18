# ADR-0019: conversa sem consulta

## Status
Aceito — 2026-09-18.

## Contexto
O planejador tinha quatro saídas: consultar, perguntar de volta, "não sei" e
fora de escopo. "Quem é você?" caía em "não sei" e a tela mostrava o selo
"Dado não disponível". O usuário quer também conversar com a IA sobre o que
viu ("o que pode ter causado a queda em julho?"), sem que toda mensagem vire
consulta.

O risco é óbvio: o ADR-0010 diz que todo número vem de uma consulta
registrada, e uma saída sem consulta poderia virar a porta dos fundos para
número inventado.

## Decisão
1. Nova intenção `conversation` (e decisão `AIReply.Decision.CONVERSATION`)
   para cumprimento, pergunta sobre o assistente, conceito do negócio que
   está no documento de referência e leitura do que já apareceu na conversa.
2. **Número só com fonte, também na conversa**: a resposta pode citar
   número que está na pergunta ou em mensagens anteriores da conversa (que
   vieram de consulta). Número novo reprova a checagem e sai um texto de
   reserva pedindo período e recorte para consultar.
3. Interpretação é hipótese, não causa: o prompt manda dizer o que os dados
   mostram e o que não mostram, sugerir quais dados confirmariam e oferecer
   a consulta.
4. Mensagem sem tema reconhecido vai com contexto mínimo (regras gerais,
   índice e mapa dos temas), e não com o documento inteiro. Se precisar de
   dado, a IA pede a seção pela saída `PRECISO DA SEÇÃO` (ADR-0015).
5. A tela mostra "Pensando…" até a consulta sair; só quando o orquestrador
   chama o banco a pergunta passa a `processing` e a tela troca para
   "Consultando os dados".
6. A regra fixa de ajuda passa a responder como conversa, com os cinco
   temas do documento em vez dos 96 títulos de consulta, e deixa de
   capturar "o que pode ter causado…" (o "você" era opcional no padrão).

## Consequências
- Medido em 2026-09-18: "Quem é você?" custou US$ 0,002 (antes ~US$ 0,09
  com o documento inteiro); a interpretação da queda de fevereiro custou
  US$ 0,03 e veio como hipótese, oferecendo consultar.
- A mesma rodada mostrou que a redação chamou "777 unidades" de "777 mil"
  por ver `und / 1000` no SQL; o prompt de redação passou a proibir mudar a
  escala do número. A checagem de ancoragem não pega esse tipo de erro
  (o número está certo, a unidade não), então ele fica coberto pelo prompt
  e pelos casos de validação.
