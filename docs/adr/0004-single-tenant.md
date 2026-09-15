# ADR-0004: Single-tenant

## Status
Aceito — 2026-09-14

## Contexto
O chatbot atende somente a Ease Labs, com um único banco de negócio e um
único catálogo mantido pelo time de BI.

## Decisão
Nenhuma dimensão de organização/tenant no schema. Permissões por usuário e
grupo do Django.

## Consequências
- Modelo de dados simples, sem `tenant_id`.
- Credenciais (OpenAI, RDS) configuradas uma vez por ambiente.
- Atender outra empresa exigiria migração de schema não trivial — risco
  aceito.
