# ADR-0029: Áudio no WhatsApp, transcrito pela OpenAI

## Status
Aceito — 2026-09-25.

## Contexto
Com o Jarvis no ar no WhatsApp (ADR-0028), o Rubens pediu que ele entenda
áudio: perguntar falando, ou pedir "preenche a planilha que vou te mandar" e
mandar o arquivo em seguida. Até aqui o Jarvis respondia "Ainda não ouço
áudio".

Regras pedidas:

1. **Privado:** responder todo áudio de contato liberado.
2. **Grupo:** responder só quando ouvir "Jarvis" no áudio.

No chat web isso já existe de outro jeito: o ditado pelo microfone, feito
pelo próprio navegador.

## Decisão

**Transcrição pela OpenAI (`gpt-4o-mini-transcribe`)**, em português, com um
vocabulário da casa no prompt (Jarvis, PX, sell out, as redes). A mesma chave
da IA já usada pelo Jarvis; o modelo pode ser trocado por
`WHATSAPP_MODELO_TRANSCRICAO`. O áudio transcrito vira a pergunta escrita e
segue o caminho de sempre: regras, cota, planejamento, ancoragem, auditoria.
A pergunta gravada é a transcrição, visível no chat web.

**Quais áudios são transcritos** (decisão do Rubens, 2026-09-25: "os dois"):

- **Privado:** todo áudio de contato liberado.
- **Grupo liberado:** o áudio que **responde (cita) uma mensagem do Jarvis**
  é atendido direto, sem precisar dizer o nome. Os demais são transcritos só
  para procurar "Jarvis" (e as grafias que a transcrição produz para ele); se
  o nome não aparece, a transcrição é **descartada na hora**: nem a mensagem
  nem o texto são gravados ou logados.
- **Grupo não liberado e número não liberado:** nada é baixado nem transcrito.

**O que a pessoa vê:** a resposta começa com `🎙️ Ouvi: "…"` (decisão do
Rubens), para perceber na hora um áudio mal entendido.

**Arquivo depois do áudio.** Arquivo sem legenda vira "Segue o arquivo.", e
o planejador segue o pedido anterior da conversa quando houver ("preenche com
o sell out"); sem pedido anterior, descreve o arquivo e oferece preencher. No
grupo, o arquivo sem marcação conta como chamada quando vem da mesma pessoa
que chamou o Jarvis nos últimos 5 minutos.

**Limites:** áudio acima de 3 minutos não é transcrito (a pessoa é avisada no
privado ou quando citou o Jarvis). Áudio que não vira texto pede para
repetir. O "parar" continua só por texto.

## Consequências
- **Custo:** a transcrição é cobrada por minuto de áudio (~US$ 0,003), não por
  token, e procurar o nome é busca no texto, sem chamada de modelo. Um grupo
  com 20 áudios de 30 s por dia custa ~US$ 0,90 por mês; um muito ativo (100
  áudios de 1 min por dia), ~US$ 9. O teto de 3 minutos limita o pior caso.
- **Privacidade:** muda a promessa do ADR-0028 de que "conversa entre as
  pessoas do grupo nunca é lida". Nos grupos liberados, o áudio de todos passa
  pela OpenAI para a busca do nome; o que não chama o Jarvis é descartado sem
  registro. Liberar um grupo passa a incluir isso (O-18).
- **Tempo:** a resposta a um áudio leva alguns segundos a mais (baixar e
  transcrever), além da espera sorteada de 3 a 30 s.
- Os testes usam o `TranscritorFake` (ADR-0005); nenhum acessa a rede.
