# ADR-0018: projetos, arquivo e exclusão lógica de conversas

## Status
Aceito — 2026-09-18.

## Contexto
Com o chat na tela (ADR-0017), o usuário pediu para excluir conversas,
arquivá-las e agrupá-las em projetos (pastas). As três coisas mexem no
histórico, e o histórico é também a trilha de auditoria (FR-15): cada
pergunta tem o `AIReply` com a consulta executada, o custo e o motivo da
decisão, ligados à mensagem por `CASCADE`.

## Decisão
1. **Projeto** (`conversations.Project`) é uma pasta do próprio usuário:
   nome e dono. A conversa aponta para ele com `SET_NULL` — excluir a pasta
   devolve as conversas para a lista geral, nunca as apaga. Projeto de outra
   pessoa responde 404, igual à conversa.
2. **Arquivar** usa a situação que já existia (`status = archived`): a
   conversa sai da lista principal e fica numa seção recolhida. Fazer uma
   pergunta numa conversa arquivada a traz de volta — senão a resposta
   chegaria num lugar escondido.
3. **Excluir é lógico** (`deleted_at`): a conversa some da lista e da API
   do usuário (404 ao abrir), mas as mensagens, as consultas e o custo
   continuam no banco. Apagar de verdade, se um dia for preciso, é decisão
   da política de retenção (O-08) e roda como rotina, não num clique.
4. **Organizar não conta como atividade**: renomear, mover, arquivar e
   excluir não alteram `updated_at`, que ordena a lista pela última
   conversa de fato.
5. Não há mudança no que a IA sabe: projeto é só organização da tela. O
   contexto de cada pergunta continua sendo a própria conversa.

## Consequências
- O Admin mostra projeto e `deleted_at` e filtra as excluídas, para o time
  de BI ver o que foi perguntado mesmo depois de o usuário "apagar".
- O texto da confirmação de exclusão diz isso ao usuário: a conversa sai
  da lista dele, o registro de auditoria fica.
- Enquanto a O-08 não for decidida, o banco da aplicação cresce sem
  limpeza. É pouco: cerca de 10 a 30 KB por pergunta, algo como 15 a 35 MB
  por mês a 50 perguntas por dia.
