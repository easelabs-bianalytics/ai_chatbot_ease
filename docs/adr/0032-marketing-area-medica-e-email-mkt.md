# ADR-0032: Marketing no cérebro do Jarvis — Área Médica e Email MKT, sincronizados no schema `marketing`

## Status
Aceito — 2026-10-01. Primeira área além do BI ligada ao Jarvis.

## Contexto

O Rubens pediu para conectar o Jarvis ao Marketing, começando por duas
fontes, as duas com o médico como usuário final:

- **Área Médica** — o portal da Ease Labs para profissionais de saúde.
  API própria (`GET /api/usuarios`, Bearer token, 60 requisições por minuto).
  Em 2026-10-01: 3.849 cadastros (730 de 2026), baixados em 1,8 s.
- **Email MKT** — o ActiveCampaign (API v3, header `Api-Token`, 5 requisições
  por segundo). Em 2026-10-01: 17.954 contatos, 60 campos personalizados (CRM,
  UF do Conselho, especialidade, categoria, representante, "Já prescreve
  Ease?"...), 66 listas, 132 tags, 563 campanhas.

E três perguntas de exemplo, que cruzam as áreas: médicos da Área Médica
cadastrados em 2026 contra os prescritores Ease de fora dela; médicos do
painel da Força de Vendas que estão na Área Médica, por representante; a base
do Email MKT com uma coluna dizendo quem está na Área Médica. Exigência dele:
**o médico se liga entre bases pelo CRM LINK (UF + CRM), normalizado dos dois
lados**, e o Jarvis tem de saber disso no prompt.

## Decisão

### 1. Sincronização diária, não consulta na hora
As APIs não são chamadas durante a pergunta. Puxar o Email MKT inteiro leva
~180 chamadas e uns 3 minutos; a pergunta tem de responder em segundos, e o
cruzamento com o BI precisa ser SQL para o número continuar vindo de cálculo
(ADR-0010). Um comando (`manage.py sincronizar_marketing`) puxa as duas fontes
e grava no schema **`marketing`** do banco `easelabs`, ao lado de `audit` e
`cddd`. Medido em 2026-10-01: **3 min 16 s** para as duas.

- Cada fonte numa transação: `DELETE` e regrava (não `TRUNCATE`, que trava a
  tabela — quem pergunta durante a carga vê a versão anterior até o `COMMIT`).
- Fontes independentes: se uma API cair, a outra é atualizada, e a que caiu
  fica com o dado da véspera.
- A Área Médica que perde cadastro no meio da paginação (veio menos que o
  `total`) falha em vez de gravar a base pela metade.
- **Frescor**: toda carga fica em `marketing.sincronizacoes` (início, fim,
  status, linhas, erro). A resposta diz de quando é o dado.
- **Retrato diário de acessos** (`area_medica_acessos_diarios`): a API não tem
  a data do último login, só a contagem. "Acessou no período" é a contagem ter
  subido entre dois retratos — vale a partir de 2026-10-01. O pedido de um
  campo `ultimo_acesso` foi feito ao time da Área Médica.

### 2. Uma role que escreve só no `marketing`
`jarvis_mkt_sync` é dona do schema e só dele: não enxerga `jarvis` (as
perguntas de todo mundo) nem os schemas de negócio. O `bi_chatbot_ro` ganha
`USAGE` e `SELECT` (inclusive nas tabelas futuras, por default privilege). A
aplicação web e o worker continuam sem escrever no banco de negócio
(ADR-0002, ADR-0008). Script: `infra/rds/05_criar_schema_marketing.sql`.

### 3. Task agendada no padrão da casa
EventBridge Scheduler → `ecs:RunTask`, como o `sync` do Cockpit: task
definition própria (`cockpit-prod-jarvis-sync`, um container, a mesma imagem
do Jarvis, sem Redis), todo dia às **5h de Brasília**. Falha deixa a marca
`SINCRONIZACAO_MARKETING_FALHOU` no log, e um metric filter avisa no tópico de
alertas do Jarvis. Os dois tokens e a senha da role vão para o Secrets
Manager; as URLs, para variável de ambiente.

### 4. CRM LINK
`marketing/crm.py`: `upper(UF) + lpad(dígitos, 7, '0')`, o formato de
`audit.medico.crm` (133.337 de 133.337 com nove caracteres, conferido no RDS).
A UF vem do campo próprio (Área Médica: `uf`; Email MKT: "UF do Conselho",
depois "UF", depois "Estado de atuação") e, se faltar, da que estiver escrita
no próprio CRM (`SP123456`, `123456/SP`, `CRM-PR 25111`). Sem UF, sem link —
número solto não identifica médico. Toda tabela de médico do `marketing` traz
a coluna `crm_link` pronta.

No prompt, a regra está nas **regras gerais** do documento de referência
(vão em toda pergunta): o médico liga pelo CRM LINK e só por ele; qualquer
outra fonte (planilha anexada, campo de texto) se normaliza na consulta, dos
dois lados; e-mail só como reserva, dito na resposta.

### 5. Conhecimento do Marketing
Seção nova no documento de referência, **"7. Marketing — Área Médica e Email
MKT"** (tema `marketing` no roteamento por palavra-chave, ADR-0015): as
tabelas, o que é cada campo, as armadilhas (Email MKT não é só médico;
inscrito em lista é `status = 1`; a tag "Inativo" é engajamento, não cadastro
desativado; `crm_cro` pode ser CRO/CRMV/CRF; CRM `PENDENTE`/UF `ER` sem link;
59% dos CRMs da Área Médica estão em `audit.medico` — quem não está não
aparece na auditoria, o que não é "não prescreve") e oito consultas de
referência, M00 a M07, entre elas as três perguntas do Rubens.

### 6. Só médico ganha CRM LINK
Achado na primeira carga de produção: a Área Médica tem dentistas e
veterinários, e o Email MKT tem farmacêuticos e balconistas. O número do
conselho deles não é CRM — o CRO PR 33262 de um dentista casaria com o CRM PR
33262 de um médico. A coluna `conselho` (CRM, CRO, CRMV, CRF) sai da
especialidade e da profissão, e só `conselho = 'CRM'` ganha `crm_link`. E o
CRM do RJ perde o `52` do CREMERJ quando vem com ele (`52.12345-6`): tirá-lo
recuperou 55 dos 90 CRMs longos do RJ.

## O que foi considerado e ficou de fora
- **Consultar as APIs na hora** (como a planilha anexada, ADR-0031): lento
  para o Email MKT e sem como fazer JOIN com o BI no banco.
- **Escrever pelo `jarvis_app`** num segundo schema: daria à aplicação web a
  escrita no banco de negócio. A role própria mantém a separação.
- **Celery beat** dentro da task do Jarvis: rodaria duas vezes com duas tasks,
  e não é o padrão da casa.
- **Cliques e aberturas por contato e por campanha** (152 mil e 108 mil
  registros): ficam para depois. Por enquanto, a última abertura e o último
  clique de cada contato e os totais de cada campanha.

## Consequências
- O Jarvis cruza Marketing e BI em SQL, pelo CRM LINK, com o dado de até um
  dia atrás e dizendo de quando é.
- O preâmbulo do documento cresceu ~250 tokens (a regra do CRM LINK), no
  prefixo que o cache reaproveita.
- A partir daqui o bump de imagem atualiza duas task definitions: a do
  service e a do sync (as duas usam `jarvis_container_image`).
- Teste local: `infra/analytics_db/init/04_schema_marketing.sh` cria o mesmo
  desenho no banco sintético.
