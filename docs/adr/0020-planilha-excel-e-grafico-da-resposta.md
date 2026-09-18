# ADR-0020: planilha Excel e gráfico da resposta

## Status
Aceito — 2026-09-18.

## Contexto
Duas coisas que o usuário pediu depois de usar a ferramenta: ver a evolução
em gráfico, em vez de ler uma tabela de doze meses, e receber uma lista
grande em `.xlsx` formatado, para trabalhar nela — tanto quando pede
("me manda em Excel") quanto quando a resposta traz uma lista longa demais
para caber na conversa.

A restrição é a de sempre (ADR-0010): nenhum número pode vir do modelo. E a
de custo: nada que faça a IA gerar HTML, SVG ou uma tabela inteira de novo,
porque token de saída é o caro.

## Decisão

**Gráfico.** A IA sugere apenas `{tipo, x, series, titulo}` junto com o
texto da resposta — algumas dezenas de tokens. O orquestrador confere a
sugestão contra o resultado de verdade: tipo conhecido, coluna `x` que
existe, séries que existem e são numéricas (no máximo três), pelo menos duas
linhas, título sem número que não esteja no resultado. O que não passa vira
"sem gráfico": melhor nenhum do que um errado. O desenho é feito no
navegador pelo Chart.js 4.4.7 (MIT), servido pela própria aplicação — em
produção o contêiner roda dentro da VPC e não deve depender de CDN.

Quando há gráfico, a consulta guarda o resultado inteiro em `result_sample`
(em vez das cinco linhas de amostra), que é o que a API manda para a tela
desenhar.

**Planilha.** O botão "Baixar Excel" aparece em toda resposta que rodou
consulta, e fica destacado quando o usuário pediu a planilha. O download
roda **a mesma consulta de novo**, revalidada pelo `sql_guard` com
`EXPORT_MAX_ROWS = 50.000` — bem acima do limite da conversa, porque o
arquivo não passa pela IA e não custa token. O arquivo é montado com
openpyxl: cabeçalho índigo, bordas, zebra, filtro, primeira linha congelada,
datas e números no formato brasileiro, códigos (CNPJ, EAN, CRM) como texto —
como número o CNPJ perde o zero à esquerda e vira notação científica — e uma
aba "Informações" com a pergunta, o momento, as linhas, a referência e a
consulta executada.

Quando o usuário pede planilha, a redação fica curta e aponta para o botão,
em vez de repetir a lista; com mais de 20 linhas e sem pedido, a resposta
mostra no máximo 10 e menciona a planilha. Pedido de planilha não gera
gráfico.

Cada download fica registrado em `DataExport` (quem, de qual resposta, qual
consulta, quantas linhas, quanto demorou): é o caminho pelo qual muita linha
sai da ferramenta.

## Consequências
- Custo praticamente zero: o gráfico acrescenta poucos tokens de saída e a
  planilha nenhum — ela não passa pelo modelo.
- O gráfico é o único ponto em que a tela recebe o resultado inteiro. Com
  500 linhas por consulta, a estimativa é de 50 a 100 MB por mês de
  `result_sample` a 50 perguntas/dia; entrou na Fase 9 junto com a política
  de retenção.
- A planilha pode demorar mais que a resposta (roda a consulta de novo, sem
  o limite pequeno): o botão mostra "Gerando planilha…" e o tempo máximo de
  consulta do catálogo continua valendo.
- Chart.js versionado no repositório (205 KB): é dependência de navegador,
  não entra no `uv`. Atualizar é trocar o arquivo e conferir a licença.
