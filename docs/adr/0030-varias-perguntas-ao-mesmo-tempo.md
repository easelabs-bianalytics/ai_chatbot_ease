# ADR-0030: Várias perguntas ao mesmo tempo, uma de cada vez por conversa

## Status
Aceito — 2026-09-30.

## Contexto
Com o Jarvis em grupos do WhatsApp, várias pessoas o marcam ao mesmo tempo.
O worker rodava com `-P solo`: uma pergunta por vez, para todo mundo. Uma
resposta de 30 s travava a fila do WhatsApp **e** do chat web, e cinco
perguntas juntas faziam a última esperar uns três minutos.

Rodar várias em paralelo, sem mais nada, abria outros problemas:

- **Mistura na mesma conversa.** Duas perguntas do mesmo chat em paralelo:
  a segunda leria a primeira ainda sem resposta no histórico, e a resposta
  sairia misturada — é daí que viria a alucinação.
- **Ordem trocada.** A espera sorteada de 3 a 30 s do WhatsApp (contra o
  padrão de robô) podia fazer a segunda pergunta ficar pronta antes da
  primeira.
- **Quem perguntou.** O grupo é uma conversa só, e o planejador não sabia
  quem escreveu cada mensagem: o "e em julho?" do Bruno virava seguimento
  da pergunta da Ana.
- **"Parar" de um, cancelando o de todos**, e, no privado, duas respostas
  seguidas sem dizer a qual pergunta cada uma é.

## Decisão

1. **Worker com `-P threads -c 4`.** Quase todo o tempo de uma resposta é
   espera pela OpenAI e pelo banco, então threads bastam: mesma memória, sem
   processo a mais, sem custo de IA a mais. O provider é criado a cada
   tarefa; os únicos estados globais são caches só de leitura (catálogo e
   documento de referência); o executor abre uma conexão por consulta.
2. **Fila por conversa (`messaging/fila.py`).** Conversas diferentes em
   paralelo; na mesma conversa, uma pergunta de cada vez, na ordem de
   chegada.
   - WhatsApp: a mensagem só é gravada depois da espera sorteada, então o
     webhook tira uma **senha** por chat no Redis; a tarefa só atende na sua
     vez e passa a vez ao terminar (respondendo, ignorando ou falhando).
   - Chat web: a mensagem já está gravada quando a tarefa roda; ela espera
     enquanto houver pergunta mais antiga da conversa pendente.
   - Quem chega fora da vez olha de novo a cada 2 s. Se a vez não anda por
     8 minutos (o worker caiu no meio de uma tarefa), a fila pula a senha
     perdida em vez de travar a conversa.
3. **Nome de quem perguntou, no grupo.** O histórico e a pergunta vão ao
   planejador como `[Ana Souza] vendas de agosto`; o prompt manda ligar o
   seguimento à última pergunta da mesma pessoa. No banco, a pergunta fica
   como a pessoa escreveu.
4. **"Parar" no grupo cancela só as perguntas de quem pediu.**
5. **No privado, a resposta cita a pergunta** quando outra mensagem já
   chegou depois dela.

## Consequências
- Quatro chats respondidos ao mesmo tempo; o quinto espera o primeiro
  terminar. Com um grupo e três conversas no chat web, ninguém espera.
- Na mesma conversa a ordem é garantida, e uma resposta nunca lê outra pela
  metade.
- A cota é conferida na hora da pergunta; duas perguntas da mesma pessoa em
  conversas diferentes, no limite exato, podem passar juntas (a diferença é
  de uma pergunta).
- A mudança de infra é só o comando do worker (`jarvis.tf`), sem recurso
  novo; tudo o mais é código do Jarvis.
