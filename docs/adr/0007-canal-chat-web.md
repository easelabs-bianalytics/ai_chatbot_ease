# ADR-0007: Canal de chat web

## Status
Aceito — 2026-09-14

## Contexto
O canal é um chat web para usuários internos, não WhatsApp. O
processamento é assíncrono (ADR-0003), então a resposta não volta na mesma
requisição do envio.

## Decisão
- Interface em templates do Django com JavaScript simples, sem build de
  frontend, servida pela mesma imagem.
- API DRF autenticada por sessão + CSRF:
  - `POST /api/conversations/` cria conversa;
  - `POST /api/conversations/<id>/messages/` envia pergunta (`202`);
  - `GET /api/conversations/<id>/messages/?after=<id>` busca novas
    mensagens (polling).
- **Idempotência:** o navegador gera um `client_message_id` (UUID) por
  pergunta; campo único no banco. Clique duplo ou reenvio por falha de rede
  devolve a mensagem existente sem reprocessar.
- `WebChannel` implementa `Channel`: `parse_inbound` valida o payload da
  API; `send_text` persiste a mensagem de saída que o polling entrega.
- `GET /api/health/` público, sem consultar banco, para o healthcheck.

## Consequências
- SSE/WebSocket ficam fora do MVP; polling basta para o volume interno.
- Não há token de webhook na URL como na referência: o acesso é por login.
