# ADR-0031: Motor de anexos 3.0 — a planilha como tabela da consulta, com plano de mudança e conferência

## Status
Aceito — 2026-09-30. Revisa o ADR-0024 (anexos) nos pontos marcados abaixo.
É o primeiro passo do Jarvis 3.0; prints ficam para o passo seguinte.

## Contexto

O motor do ADR-0024 fazia duas coisas: ler a **forma** da planilha (cabeçalho,
tipo, oito exemplos) e **preencher** colunas casando a chave da planilha com a
chave do resultado. O conteúdo nunca chegava a lugar nenhum — nem ao modelo,
nem ao banco. Na prática, o Jarvis "só preenchia células", e mal.

Duas conversas reais mostraram o limite:

**Conversa 44 (Paulo, 2026-09-29)** — 230 médicos com CRM; pedido: a UTC de
cada um, o território da UTC e o representante numa coluna nova.

1. Sem acesso aos 230 CRMs, o planejador escreveu uma consulta sobre
   `audit.medico` inteiro. Ela rodou duas vezes (500 linhas para a resposta,
   50 mil para o preenchimento), foi cortada, e **84 de 230** foram
   preenchidos.
2. Sabendo o que faltava, o modelo inventou `WHERE m.crm = ANY(:crms_planilha)`
   — um parâmetro que não existe. Erro de sintaxe, resposta falhou.
3. A planilha era descartada no primeiro preenchimento: na correção seguinte
   o Jarvis pediu o arquivo de novo e, reenviado, errou igual.
4. Só funcionou quando o Paulo **colou os 230 CRMs no texto** — o modelo fez
   um `VALUES` e casou 224. Era a prova de que a solução é pôr os dados da
   planilha dentro da consulta.
5. A mesma mensagem dizia "não é seguro preencher a planilha" (redação) e
   "Preenchi 84 de 230 linhas" (sistema): duas vozes, nenhuma conferência.

**Conversa 37 (2026-09-25)** — pedido do representante e do GR de cada médico:
o Jarvis foi pelo painel (a referência dizia isso), a pessoa corrigiu ("puxe a
UTC do médico pelo CRM, não ligue pelo painel"), e a segunda resposta perdeu a
tarefa — virou uma exportação genérica de 500 linhas. E o "228 de 230
preenchidas" contava linha com valor vazio como preenchida.

O documento de requisitos do Jarvis 3.0 pede, para o Excel: entender a
finalidade da planilha, preservar a base por padrão, classificar a operação
(UPDATE, ENRICHMENT, ANALYSIS, TRANSFORMATION, REPORTING), perfilar sem modelo,
separar a camada de dados da de workbook, um plano de mudança antes de
alterar, conferência do Excel e justificativa de toda alteração.

## Decisão

### 1. Perfil determinístico (`attachments/planilha.py`)
Sem modelo, sem pandas (openpyxl já estava lá e o pandas custaria ~60 MB de
imagem para o que cabe em 100 linhas): por aba,

- **onde está o cabeçalho** — a primeira linha, entre as 20 primeiras, com
  pelo menos metade da largura da mais larga e maioria de texto (planilha
  real abre com título);
- **cada coluna**: nome, nome no SQL (`Nome do médico` → `nome_do_medico`),
  tipo, quantas linhas têm valor, quantos valores diferentes, se **serve de
  chave** (todas preenchidas e diferentes) e se é **calculada** (fórmula,
  lida numa segunda passada sem `data_only`);
- **as linhas**, com o número de cada uma no arquivo (`_linha`), guardadas em
  memória para a camada de dados.

O que sobe ao modelo é o resumo disso — o mesmo teto de 4.000 caracteres.

### 2. A planilha é uma tabela: `anexo.<aba>` (`attachments/anexo_sql.py`)
O modelo escreve `FROM anexo.painel a LEFT JOIN audit.medico m ON ...` como
escreveria com qualquer tabela. Antes de executar, o executor da conversa
troca `anexo.painel` por uma CTE:

```sql
WITH anexo__painel(_linha, "crm") AS (SELECT * FROM unnest(%s::bigint[], %s::text[]))
SELECT * FROM ( ...consulta do modelo, com anexo.painel → anexo__painel... ) AS bi_guard_q LIMIT 501
```

- Os valores vão como **parâmetro do driver**, nunca colados no SQL: célula
  com aspas ou `;` é dado do `unnest`. Testado no Postgres real (sintético),
  em transação READ ONLY.
- Só vão as colunas que a consulta cita (todas, com `*`): 20 mil linhas × 60
  colunas não viram 1,2 milhão de valores para a consulta usar três.
- O validador (`sql_guard`) aceita `anexo.<nome>` só para as abas da planilha
  da conversa; aba que não existe volta à correção com a lista das certas.
- A consulta **parte da planilha** (`LEFT JOIN`): uma linha por linha dela,
  inclusive a que não casou. Nada de varrer o cadastro e casar depois.

**Isto não muda a regra "só a forma sobe ao modelo" (ADR-0024).** O conteúdo
vai ao banco, que é somente leitura; ao modelo continua subindo o perfil. O
custo da pergunta não cresce com o tamanho da planilha.

### 3. Plano de mudança (saída estruturada do planejador)
As regras moram em `prompts/planilha_v1.md`, que só entra no contexto quando
há planilha. O plano passa a trazer:

- `operacao_da_planilha`: `descrever`, `enriquecer` (ENRICHMENT), `atualizar`
  (UPDATE), `analisar` (ANALYSIS), `transformar` (TRANSFORMATION) ou
  `relatorio` (REPORTING);
- em `preenchimento`, a chave `_linha` e, por coluna, `justificativa` (o que
  é e de onde vem) e `sobrescrever` (só com pedido explícito);
- `aba_nova` e `grafico_na_aba`, no plano e em cada entrega de `consultas`:
  o resultado vira uma aba nova, com gráfico nativo do Excel.

### 4. Camada de workbook
- **Preenchimento pela `_linha`**: o valor volta à linha de onde veio. Linha
  repetida no resultado fica em branco (escolher uma seria inventar). Linha
  que casou mas veio vazia **não conta como preenchida**, e é citada pelo
  identificador.
- **A base é preservada por padrão**: coluna nova entra no fim, com o estilo
  do cabeçalho vizinho; em coluna que já existe, só a célula vazia recebe
  valor, a não ser com `sobrescrever`. Fórmulas continuam fórmulas (a escrita
  abre sem `data_only`; `.xlsm` mantém as macros).
- **Aba nova** para relatório e transformação; CSV que ganha aba vira `.xlsx`
  com a base na aba "Dados".
- **Aba "Notas do Jarvis"** em todo xlsx devolvido: onde, o que mudou, por
  quê, de onde veio o dado e quanto preencheu. Substituída se a pessoa
  mandar de volta o arquivo que o Jarvis devolveu.

### 5. Conferência antes de entregar (`attachments/qa.py`)
Compara o original com o que vai sair, célula a célula (fórmula como texto):
toda aba original presente, nenhuma linha a mais ou a menos, **nenhuma célula
original com valor alterada** fora das colunas com `sobrescrever`, célula
vazia só preenchida nas colunas de destino, aba nova só as pedidas e as
notas. **Qualquer problema barra a entrega** ("Não entreguei a planilha…") e
vai ao log como erro — é defeito nosso. Resultado cortado no limite também
não vira arquivo: a planilha pela metade é pior que nenhuma.

A conferência mede também a cobertura de cada coluna escrita e o valor que a
domina ("**SEM REP** aparece em 146 das 224 linhas"), que é o achado que a
pessoa precisa ver.

### 6. Uma voz só na resposta
A planilha é alterada e conferida **antes** da redação, que recebe o
relatório (`AnswerRequest.planilha_devolvida`) e é instruída a falar do
arquivo com esses números — e não a dizer que "não é seguro preencher". Os
números do relatório contam como fonte na ancoragem (ADR-0010). A nota
determinística no fim continua.

### 7. A planilha acompanha a conversa
Duas horas desde o último uso (`SEGUNDOS_DA_PLANILHA_NA_CONVERSA`), renovadas
a cada mensagem que a usa; o preenchimento não a descarta mais. Para de
seguir quando uma resposta com dado **não** a usou (consulta sobre `anexo.*`,
preenchimento, aba nova ou planilha pendente contam como uso). Continua sendo
Redis com prazo: nada vai para disco, S3 ou banco.

O "Baixar Excel" de uma resposta que consultou a planilha refaz a consulta
com ela enquanto estiver no depósito; depois, responde 410 com o motivo.

### 8. Regra de negócio: o responsável pelo médico é o da UTC
Decisão do Rubens (2026-09-30): o representante e o GR responsáveis por um
médico saem da **UTC do endereço** (`audit.medico.utc_codigo` →
`cddd.forca_vendas` → `fv_territorio` → `fv_distrito`); o painel só quando o
pedido falar em painel. Uma UTC tem um território só. Está no documento de
referência (A22) e num caso de validação.

## O que foi considerado e ficou de fora
- **DuckDB/SQLite em memória** para as contas sobre a planilha: o Postgres já
  faz, a CTE serve às duas coisas (cruzar com o banco e analisar só a
  planilha), e uma segunda máquina de SQL seria um segundo dialeto para o
  modelo e para o validador.
- **Mandar as linhas ao modelo**: é o custo que o ADR-0024 existe para evitar
  (1 a 2 milhões de tokens numa planilha grande), e a resposta seria pior —
  o modelo leria, o banco calcula.
- **Tabela temporária**: a transação é READ ONLY por desenho (ADR-0008); a CTE
  dispensa escrita.
- **Revisão crítica por uma segunda chamada ao modelo**: a conferência
  determinística cobre o que dá para conferir sem opinião (preservação,
  cobertura, repetidas, corte), sem custo e sem latência. Fica como próximo
  passo se as avaliações mostrarem erro de interpretação que a conferência
  não pega.

## Consequências
- O pedido da conversa 44 vira **uma consulta, uma execução**, sobre as 230
  linhas, com o arquivo conferido — sem colar CRM em texto.
- O custo por pergunta com planilha fica praticamente igual: o prompt da
  planilha tem ~1.600 tokens (o bloco antigo, no código, tinha ~600), só
  quando há planilha — ~US$ 0,002 a mais no Terra — e a execução dupla some.
- O modelo pode analisar a planilha (`GROUP BY` sobre `anexo.*`) e gerar abas
  de relatório com gráfico, com números de cálculo real.
- A interface do executor ganhou `params` — só o executor com anexo os usa.
- A planilha fica até duas horas no Redis (antes, 15 min). A task tem 1 GB, e
  o teto de 5 MiB por arquivo continua.
- Arquivo devolvido ganha a aba "Notas do Jarvis". Quem importa a planilha em
  outro sistema pode precisar apagá-la; o nome é fixo para isso ser fácil.

## Revisão — testes com planilhas reais (2026-10-01)

Rodados com o modelo e o RDS reais (`gpt-5.6-terra` / `luna`), em três
arquivos do time: o painel da Simone (230 médicos), os cadastros do Balcão
Seguro (513 linhas) e o Racional de Metas 2T26 (8 abas, fórmulas entre abas,
duas pastas externas, aba oculta). Custo total dos testes: ~US$ 1,60.

| Caso | Resultado |
|---|---|
| Representante e GR de cada médico | 200 de 230 na primeira mensagem, uma consulta, pela UTC (A22) |
| Representante da indicação no Balcão | 465–493 de 513: CNPJ → PDV → brick, e cidade/UF de reserva, com a coluna "Critério de identificação" |
| Entender o Racional de Metas | explica o racional pelas fórmulas e faz revisão crítica (ajustes manuais, comentário da direção, 32 × 35 representantes, `#DIV/0!`, aba oculta, links externos) |
| "Como é calculada a meta do Hermes?" | 515 ÷ 7.808 = 6,5957% × 8.634,5 = 569,5, menos o `-8` manual da fórmula = 561,5 gravado |
| Regra "meta ≥ 3× o custo incremental" | checada com método explícito (incremento de meta × incremento de custo, só nos promovidos) |
| Nomes entre abas | 25 diferenças, conferidas fora do modelo |
| Análises sobre a planilha | por UF/função, CPF em várias farmácias (nenhum — conferido), 42 médicos com 108 PX Ease em jun–ago/26 |

O que os testes mostraram e foi corrigido:

- **Pasta de trabalho de racional.** A tabela principal termina onde a
  coluna-âncora (a mais preenchida no começo) fica vazia três linhas seguidas;
  totais e blocos de premissas abaixo dela entram no perfil por linha
  ("L40: A=ISOLADO 30 ML B=758.5 … K=8634.52"), e não como linhas da base.
  O perfil traz a letra e a fórmula de cada coluna calculada, os comentários
  das células, aba oculta e pastas externas. Exemplos curtos (40 caracteres)
  e sem repetição; coluna de número com um "-" ou "Neo" continua número.
- **`anexo.<aba>_celulas`**: toda aba de até 20 mil células vira também uma
  grade (`_linha`, coluna, valor, numero, formula), de onde o modelo lê a
  premissa em K40 ou a fórmula de uma célula. É assim que ele explicou o `-8`.
- **Teto do resumo** cresce com as abas: 4.000 caracteres + 4.000 por aba a
  mais, até 32.000 (~8 mil tokens, ~US$ 0,016 no planejador, só em pasta
  desse tamanho), dividido entre as abas — a pequena devolve o que não usou.
- **Prompt da planilha**: descrição de racional em seções (para que serve,
  como os números nascem, premissas, ligações, revisão crítica, o que dá
  para fazer); várias pistas com reserva e coluna do critério; fórmula e
  diferenças calculadas na consulta; `FILTER` só com agregação.
- **Ancoragem (ADR-0010)** aceita o mesmo número dito de outro jeito:
  arredondado com separador de milhar ("8.635" de 8.634,52), fração em
  percentual ("6,60%" de 0,0659), em escala ("28,6 mil"), com menos casas;
  numeração de lista ("1.", "2.") não conta como dado. Diferença calculada no
  texto e percentual errado continuam barrados (há teste para os dois).
- **Validador**: função que devolve linhas (`regexp_split_to_table`,
  `generate_series`) não é mais lida como "tabela sem schema"; o nome dela
  continua passando pela lista de funções bloqueadas.
- **Conferência**: números comparados com tolerância relativa de 1e-12 — o
  openpyxl regrava com 16 algarismos o que veio com 17, e isso barrou uma aba
  nova legítima.
- **Preenchimento**: valor de texto sem espaço/TAB nas pontas; aba com o
  nome do arquivo cai na única aba; no UPDATE só das vazias, a linha deixada
  de fora que já tinha valor não conta como "sem correspondência"; nenhuma
  célula escrita = nenhum arquivo.
- **Resposta**: quando nada muda, a redação recebe "a planilha NÃO foi
  alterada"; com várias colunas, a nota dá a cobertura de cada uma; a lista
  do que ficou em branco não repete o mesmo identificador; consulta que
  passou de 500 linhas e foi refeita inteira para a planilha não é mais
  descrita como "cortada".
- **Perfil em cache** por conteúdo (4 arquivos por processo): a planilha é
  perfilada a cada mensagem da conversa.

Corrigido mas ainda sem nova rodada real (validar no uso, depois do deploy):
a descrição completa do Racional de Metas (o rascunho caía só por "28,6
mil"), a aba "Resumo por GR" (barrada pelo falso positivo da conferência), o
cruzamento das metas com o sell-out real (barrado pelo validador) e o UPDATE
só das células vazias.
