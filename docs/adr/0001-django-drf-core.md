# ADR-0001: Django + Django REST Framework como núcleo

## Status
Aceito — 2026-09-14

## Contexto
O chatbot precisa de um núcleo único que concentre autenticação de usuários
internos, estado das conversas, orquestração da IA e trilha de auditoria, e
de um painel administrativo para o time de BI revisar respostas, consultas
e lacunas. O projeto de referência (`avaliacao_eleitores`) já roda em
produção com essa base e o padrão de trabalho será replicado.

## Decisão
Usar Django como framework de aplicação, Django REST Framework para a API
do chat e o Django Admin como painel de auditoria no MVP.

## Consequências
- Toda regra crítica (validação de consulta, ancoragem numérica, auditoria)
  vive no backend, nunca no navegador.
- Migrations do Django evoluem apenas o banco da aplicação — o banco de
  negócio não é gerido pelo Django (ver ADR-0002).
- Autenticação usa o sistema de auth do Django (ver ADR-0011).
