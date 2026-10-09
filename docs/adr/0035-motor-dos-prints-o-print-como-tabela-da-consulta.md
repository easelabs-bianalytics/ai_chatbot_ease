# ADR-0035: Motor 3.0 dos prints — o print como tabela da consulta

## Status
Aceito — 2026-10-09. É o passo seguinte do ADR-0031 ("prints ficam para o
passo seguinte") e revisa o ADR-0024 na parte da imagem. A regra "a imagem
não é guardada" continua: o que acompanha a conversa é a transcrição.

## Contexto

Até aqui o print era lido uma vez pelo modelo barato e descartado. Ele só
virava dado quando era uma tabela *a completar*. Fora isso, a resposta era o
que o leitor escrevia — inclusive conta (soma, participação, maior queda),
sem a ancoragem do ADR-0010.

Os sete prints que chegaram em produção até 2026-10-08 mostraram o resto:

| Conversa | O que aconteceu |
|---|---|
| 44 | Lista de 230 CRMs: "resolução baixa demais, cole em texto". A pessoa colou à mão. |
| 75 | Faixa larga de planilha "ilegível" — e mesmo assim o leitor escreveu uma pergunta sobre "a planilha enviada", e o planejador pediu os nomes das colunas de uma planilha que não existia (US$ 0,19). |
| 7 e 8 | Tabela a completar: funcionou (é o caminho do ADR-0024). |
| 22, 67 | Print do gráfico do próprio Jarvis com crítica ou ajuste (o 67 já resolvido na revisão de 2026-10-08). |
| 80 | "Do que se trata esse print?": funcionou. |

A causa dos dois primeiros era nossa: **todo print era reduzido a 1.280 px
no lado maior**. Um print alto de lista (131×4.726) virava uma tira de 35 px
de largura.

## Decisão

### 1. Ler sem apagar o texto (`attachments/imagem.py`)
O que manda no custo é a área; o que manda na leitura é o tamanho da letra.

- Print comum (um lado até 2,2× o outro): reduzido pela **área**, até 1,45
  milhão de pixels e 2.048 px de lado — abaixo do teto em que o modelo
  reduz por conta própria. Uma leitura, ~1.700 tokens (antes ~1.100).
- Print longo (lista, faixa): **não é reduzido para caber**. É lido em
  pedaços ao longo do lado maior, cada um do tamanho de uma leitura, com 48
  px de sobreposição, até seis pedaços. O último pedaço fica mais curto, em
  vez de recuar (recuado, repetia ~65 linhas do anterior).
- Os pedaços são lidos em sequência: o segundo recebe os cabeçalhos que o
  primeiro leu e a direção da junção (`ImageRequest.pedaco`, `pedacos`,
  `direcao`, `colunas_lidas`).

### 2. Leitura estruturada sempre (`leitor_de_imagem_v2.md`)
O leitor transcreve **todo bloco de dado** — tabela, lista, série de gráfico
com os valores escritos, cartões de indicador — com cada célula como está no
print, `"?"` no que não dá para ler. Diz também o tipo do print, a operação
(`descrever`, `completar`, `cruzar`, `conferir`, `analisar`, `transformar`),
se deu para ler e por quê. Não faz conta na resposta. Com blocos,
`pergunta_ao_banco` fica vazia.

### 3. Junção e conferência sem modelo (`attachments/transcricao.py`)
- **Junção**: lista alta continua a mesma tabela, sem as linhas repetidas da
  emenda; faixa larga põe as colunas lado a lado, só se o número de linhas
  bater (senão fica a parte da esquerda, com aviso).
- **Conferência**: largura das linhas, número escrito como o Brasil escreve
  ("1.234,56", "12,5%", "R$ 3,2 mil", "(120)") vira número; CRM, CNPJ e
  código continuam texto; linha de total sai da tabela e é conferida contra
  a soma ("fecha" ou "não fecha"); célula ilegível fica em branco e é citada
  pelo nome; código repetido numa lista é avisado.

O resumo da conferência vai ao planejador e à pessoa.

### 4. O print vira `anexo.<aba>`
Cada bloco vira uma aba de uma planilha em memória (`tabela_do_print.xlsx`),
e daí é o motor do ADR-0031: o planejador cruza com o banco pela
`anexo.<aba>` (a lista de CRMs com `audit.medico`, pelo `crm_link`), e toda
conta sobre o print é do SQL. O perfil começa dizendo que a planilha é a
transcrição de um print (`prompts/planilha_v1.md`, seção 7).

### 5. As rotas
- **Ilegível** e sem bloco: `print_ilegivel` — diz o motivo e pede o arquivo,
  o texto ou o print em partes. Sem pergunta inventada (conversa 75).
- **Transformar**: `print_em_planilha` — devolve o xlsx da transcrição com a
  aba "Notas do Jarvis" (de onde veio, o que conferir). Sem planejador.
- **Completar, cruzar, conferir, analisar**: planejador, com o print como
  tabela.
- **Descrever**: a resposta do leitor, **se todo número dela estiver na
  transcrição** (ancoragem contra os blocos). Com conta no texto, vai ao
  planejador.
- **Sem bloco** (tela, texto, gráfico sem rótulo): como antes.

### 6. Conta só sobre o print, contexto enxuto
"Qual a participação de cada rede?" sobre o print não precisa do documento
de negócio: o plano vai com o preâmbulo e a planilha (`so_a_planilha`). Se
faltar regra, o planejador pede a seção, como em qualquer pergunta.

### 7. O print acompanha a conversa
A transcrição fica no depósito por duas horas, como a planilha (ADR-0031,
7), registrada em `print_transcrito` no AIReply. "E quanto a Pague Menos
vendeu em setembro?" na mensagem seguinte usa o print sem reenviar.

## Testes com o modelo e o RDS reais (2026-10-09)

Prints montados no formato de um print de Excel; a lista tem os 224 CRMs
que a pessoa colou na conversa 44. Custo total da rodada, com as reexecuções
depois das correções: ~US$ 0,44.

| Caso | Resultado | Custo |
|---|---|---|
| Lista de 224 CRMs (conv. 44), representante e GR | 3 pedaços; 223 de 224 lidos certos, 3 com dígitos trocados (caem em "sem correspondência", à vista), 2 repetidos avisados; 200 de 227 preenchidos pela UTC (A22) | US$ 0,029 |
| Faixa larga (conv. 75), GR de cada médico | 8 de 8 lidos; 7 com GR | US$ 0,066 |
| Participação de cada rede no total | total conferido ("fecha"); 41,1% calculado no SQL | US$ 0,017 |
| Painel de indicadores (conv. 80) | só leitura, números ancorados nos cartões | US$ 0,0006 |
| "Passa esse print para Excel" | xlsx com a tabela e as notas, sem planejador | US$ 0,0005 |
| Tabela a completar (conv. 7) | 3 de 3, VAR % calculada | US$ 0,046 |
| Print ilegível | `print_ilegivel`, sem pergunta inventada | US$ 0,0003 |

O que a rodada mostrou e foi corrigido antes de fechar: o último pedaço
recuado (290 linhas para 224), o leitor listando os CRMs em
`pergunta_ao_banco` (o planejador copiou 96 num `VALUES` e preencheu 84) —
pedido longo do leitor não entra mais na pergunta — e o contexto completo
na conta só sobre o print (US$ 0,089 → 0,017).

## Consequências
- A leitura do print comum custa um pouco mais (~1.700 tokens contra
  ~1.100, ~US$ 0,0002 a mais); a do print longo, até seis leituras
  (~US$ 0,005). A saída da leitura sobe de 1.500 para até 8.000 tokens.
- Print que vai ao planejador custa o que custa uma pergunta com planilha:
  ~US$ 0,02 (conta só sobre o print) a ~US$ 0,07 (cruzar com o banco).
- Leitura de imagem erra dígito: ~1% nos CRMs do teste. A conferência não
  sabe o valor certo; o que não casa com o banco aparece pelo nome, e a
  resposta e as notas dizem que o dado veio do print.
- A transcrição fica guardada na conversa (ADR-0034) como entrada, como a
  tabela do print já ficava. A imagem continua descartada depois da leitura.
- O nome `tabela_do_print.xlsx` e a aba "Tabela do print" continuam; com
  vários blocos, as abas são "Print 1", "Print 2" (ou o título do bloco).
