"""Bases do Marketing no cérebro do Jarvis (ADR-0032).

Duas fontes, as duas com o médico como usuário final:

- **Área Médica** — o portal da Ease Labs para profissionais de saúde
  (cadastro, conteúdo científico, pedido de visita técnica);
- **Email MKT** — o ActiveCampaign, canal de comunicação direta e segmentada
  com a base de contatos (campanhas, jornadas, listas e tags).

Nenhuma das duas é consultada na hora da pergunta. A sincronização diária
(`manage.py sincronizar_marketing`) grava as duas no schema `marketing` do
banco `easelabs`, e o Jarvis as cruza com o BI em SQL, como qualquer outro
schema — pelo CRM LINK (`crm.py`), nunca pelo número solto.
"""
