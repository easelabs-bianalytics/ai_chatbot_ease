# ADR-0011: Autenticação de usuários internos pelo Django

## Status
Aceito — 2026-09-14

## Contexto
O chat expõe dados de negócio da Ease Labs e consome recursos pagos (API
de IA) e do RDS. Precisa de acesso restrito a usuários internos desde o
MVP.

## Decisão
- Login por sessão do Django; usuários criados pelo administrador no Admin.
- Todas as rotas exigem login, exceto `/api/health/` e a tela de login.
- Cada usuário vê apenas as próprias conversas; superusuário vê todas no
  Admin.
- API com `SessionAuthentication` + CSRF, `IsAuthenticated` como permissão
  padrão do DRF (diferente da referência, onde a ausência de
  `REST_FRAMEWORK` deixava `AllowAny`).

## Consequências
- SSO (Google/Microsoft) fica como decisão em aberto, fora do MVP.
- A auditoria sabe quem perguntou o quê.
