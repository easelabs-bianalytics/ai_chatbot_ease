# Decisões em aberto

Rastreia decisões que dependem de terceiros ou que ainda não foram tomadas.
Nenhum item vira ADR até estar decidido — ADRs registram só decisões
tomadas (`docs/adr/`).

Regra geral adotada em 2026-09-14: **nenhuma funcionalidade que dependa de
um item desta lista é implementada antes de ele ser resolvido.** Até lá,
usa-se fake ou o banco analítico sintético local.

## Dependências externas

| ID | Dependência | Responsável | Bloqueia | Status |
|---|---|---|---|---|
| D-01 | Usuário somente leitura no RDS (ADR-0008) | DBA | — | ✅ Resolvido em 2026-09-16: `bi_chatbot_ro` com USAGE e SELECT nos schemas `audit`, `cddd`, `td`, `tdd`, `pbm` e `estoque_redes`, default privileges para os quatro donos e modo somente leitura. Quando `remuneracao_fv` existir, precisa do mesmo GRANT |
| D-02 | Rede entre a aplicação e o RDS | Infra AWS | Deploy com dados reais | Confirmado pela DBA em 2026-09-16: o RDS está em subnet privada e só aceita conexão de dentro da AWS. Railway fica descartado; a aplicação precisa rodar na mesma VPC (ECS). Faltam: regra no security group do RDS liberando o do chatbot na porta 5432, e saída para a internet (NAT) nas subnets da aplicação — requisito confirmado pelo ADR-0016, que escolheu a OpenAI. Em desenvolvimento, o acesso segue pelo túnel SSM |
| D-03 | Chave da API OpenAI no `.env` (ADR-0016) | Usuário | Fase 5 | Em coleta (2026-09-17). Vai em `AI_PROVIDER_API_KEY`, escrita direto no arquivo |
| D-04 | Catálogo aprovado (schemas/tabelas permitidos, colunas bloqueadas, dicionário), complementando `chatbot_bi_referencia_querys.md` | Time de BI | Validação (Fase 7) | Pendente |
| D-05 | Lista de usuários internos autorizados | Gestão | Go-live | Pendente |
| D-06 | Chip dedicado para o Jarvis no WhatsApp (ADR-0028): número novo, fora de qualquer grupo, aberto no aparelho a cada 14 dias | Rubens | Conectar o canal WhatsApp | Em providência (2026-09-23). Até lá, tudo roda com o cliente fake |
| D-07 | Role `jarvis_evolution` e schema `evolution` no `easelabs` (script 04 em `infra/rds/`), com snapshot antes | DBA / Rubens | Subir a Evolution em produção | Pendente |

## Decisões de produto e dados

| ID | Pergunta | Proposta | Bloqueia | Status |
|---|---|---|---|---|
| O-01 | Modelo da IA | ✅ Decidido em 2026-09-17 (ADR-0016): `gpt-5.6-terra` no planejamento e `gpt-5.6-luna` na redação. Confirmar com a prova de fogo de 20 casos | — | Decidido |
| O-02 | Colunas pessoais bloqueadas | Dado de pessoa física sai (consumidor do PBM e da `cddd.adesao`, CPF e contatos de médico e de cadastros de PDV); endereço e telefone do PDV e e-mail corporativo do representante ficam. Lista viva em `app/knowledge/catalog.yaml` | — | Ampliado em 2026-09-16 por varredura do banco real; confirmar com o time de BI |
| O-03 | Comentários livres de visitas (`audit.rx_visitas.comentarios`, Q42) podem ir para o modelo? | Liberar, pois estão na consulta validada | Q42 no catálogo | A confirmar |
| O-04 | Período padrão quando o usuário não informa | Perguntar o período antes de qualquer número | — | Decidido pelo documento de referência (2026-09-16) |
| O-05 | Cálculos derivados (crescimento, total, média) | Feitos no SQL, como a Q03 faz com o share; o modelo nunca calcula no texto (ADR-0010, ADR-0014) | — | Decidido em 2026-09-14 |
| O-06 | Limites padrão | 15000 ms, 500 linhas e 50 linhas para o modelo, já valendo em `app/knowledge/catalog.yaml` | — | Em uso desde a Fase 3; confirmar com o time de BI |
| O-07 | Quem aprova mudanças de catálogo e prompt | Time de BI | Fluxo de mudança | Pendente |
| O-08 | Retenção das conversas e da auditoria | Exclusão pelo usuário é lógica (ADR-0018); falta definir por quanto tempo guardar e quem pode apagar de verdade | Produção | Pendente — cresce ~15 a 35 MB/mês a 50 perguntas/dia |
| O-09 | SSO para login | Fora do MVP | Pós-MVP | Pendente |
| O-10 | Formato das consultas de referência | Continuam em `chatbot_bi_referencia_querys.md`, injetado no prompt, sem migração para YAML (ADR-0006, ADR-0014) | — | Decidido em 2026-09-14 |
| O-16 | Banco da aplicação (histórico, usuários, auditoria) na AWS | **Recomendado**: `CREATE DATABASE jarvis` na instância existente, com schema `jarvis` e role própria — no PostgreSQL não há acesso entre databases sem FDW, então isola quase como uma instância separada, sem custo novo. Alternativa: instância RDS própria (~US$ 15 a 25/mês). Descartado o schema dentro do `easelabs`, que colocaria o usuário com escrita no mesmo database dos dados de negócio. Desenho em `plan.md`, Fase 9. A trava do ADR-0002 precisa passar a recusar só o host de negócio | Deploy (Fase 9) | A decidir com a DBA — a instância é produção de outro produto (`cockpit-prod`) |
| O-18 | Dado de negócio em grupo de WhatsApp: a resposta fica visível para todos os membros, inclusive quem não usa o chat web | Liberar grupo a grupo no Admin, com o grupo sabendo disso; qualquer membro pode chamar (decisão do Rubens, 2026-09-23) | — | Decidido; revisar com a gestão antes de liberar grupo com gente de fora do time |
| O-15 | Uma rede pode ter mais de uma raiz de CNPJ | ✅ Confirmado pelo usuário em 2026-09-17: é normal, não é erro de cadastro. O documento de referência foi corrigido (seção 3.4): as raízes são descobertas por `ILIKE` no nome e todas entram no filtro | — | Resolvido |
| O-14 | Teto de gasto mensal com a IA | Limite configurável: aviso no Admin em 80% e recusa cordial ao atingir 100% | Produção | Proposto em 2026-09-17 (ADR-0016) |
| O-13 | Nome de pessoa que casa com mais de uma ("Alexandre") | O pipeline faz uma consulta só; o planejador traz o nome completo no resultado e a redação pergunta qual quando vier mais de um | — | Proposto em 2026-09-16; conferir nos casos E11 |
| O-11 | Checar custo com `EXPLAIN` antes de executar SQL gerado pela IA | Recusar acima de um limite de custo estimado, além do timeout | Executor (Fase 3) | A confirmar |
| O-12 | Objetos `ruptura_extrato` usados pela antiga C03 não existiam no banco | — | — | ✅ Resolvido em 2026-09-16: o documento reescrito não usa mais `ruptura_extrato`; a C03 atual lê `estoque_redes` |

## Observações operacionais

- O RDS só é acessível por túnel SSM, que **sobe sempre no WSL**: no Windows
  nativo o `session-manager-plugin` morre sem console. Qualquer sessão só
  consome a porta: `host=127.0.0.1` (não `localhost`, que tenta IPv6 antes),
  `port=15432`, `dbname=easelabs`, `sslmode=require`, `connect_timeout=15`.
  O túnel expira em cerca de 1h; se a conexão travar, reabrir no WSL.
- O `.env` foi movido para `bi/.env` em 2026-09-14 e contém credenciais
  reais (AWS). Está no `.gitignore`, nunca é lido, impresso ou commitado, e
  os testes não usam seus valores. A chave da OpenAI entra no mesmo arquivo.
