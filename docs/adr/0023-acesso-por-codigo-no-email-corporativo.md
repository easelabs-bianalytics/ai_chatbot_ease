# ADR-0023: Acesso por código enviado ao e-mail corporativo

## Status
Aceito — 2026-09-21. Substitui a forma de login da ADR-0011; o resto dela
(sessão do Django, CSRF, `IsAuthenticated`, cada um vê só as próprias
conversas) continua valendo.

## Contexto
O Jarvis expõe os dados comerciais da empresa inteira. O objetivo é que só
gente da Ease Labs use o app.

O caminho natural seria entrar com a conta Microsoft (Entra ID), que traria
a foto do perfil. Ele exige registrar um app no tenant da Ease, e o usuário
do BI não tem essa permissão; envolver a TI foi descartado. Registrar o app
num tenant nosso esbarraria no mesmo bloqueio, no consentimento.

## Decisão
- Login sem senha: a pessoa informa o e-mail e recebe um código de 6
  dígitos. Só entra quem lê uma caixa **exatamente** `@easelabs.com.br`
  (`web/acesso.py`).
- Qualquer e-mail do domínio entra; o primeiro acesso cadastra o usuário em
  `auth_user` (schema `jarvis`). O controle é no Admin: desativar alguém
  corta o acesso mesmo com e-mail válido.
- Regras: código vale 10 min e uma vez; 5 tentativas por código; pedir um
  novo anula o anterior; 60 s entre pedidos; no máximo 5 por e-mail e 20
  por IP por hora; o banco guarda HMAC, não o código; usuário desativado
  recebe a mesma resposta de quem está ativo, sem e-mail sair.
- Cada pedido fica em `CodigoDeAcesso`: quem, quando, de que IP, se usou.
- Envio pela mesma lógica do Cockpit: console no desenvolvimento, Gmail SMTP
  em produção, remetente igual à conta autenticada.
- Usuário e senha ficam desligados (`LOGIN_POR_SENHA`); a tela de senha do
  Admin redireciona para o login por código.
- Sessão expira após 30 dias sem uso.

## Consequências
- Quem sai da empresa perde o acesso quando a TI desliga o e-mail — sem
  processo nosso.
- Sem foto do perfil: continuam as iniciais.
- O login depende da entrega do e-mail. Código no spam é o risco mais
  provável; a tela avisa.
- Os administradores antigos sem e-mail são reconhecidos pelo nome de
  usuário (`rubens.filho@` → `rubens_filho`) no primeiro acesso. Quem tiver
  e-mail fora do padrão nome.sobrenome entra como usuário novo e precisa ter
  o papel ajustado no Admin.
- Migrar para a Microsoft depois continua possível: a sessão e a tabela de
  usuários são as mesmas.
