# Perguntas avançadas — treino do chatbot de BI

Perguntas de análise que **não estão cobertas** pelo [chatbot_bi_referencia_querys.md](chatbot_bi_referencia_querys.md)
e exigem raciocínio, não só um filtro. Cada uma traz a **query de referência** (ponto de partida,
não resposta pronta), o que a IA deve confirmar antes e o gabarito conferido no AWS.

**Como a IA deve usar:** identificar o padrão da pergunta, confirmar os parâmetros com o usuário
(classe de produto, canal, período, laboratório) e adaptar a query. Os parâmetros que mudam em
quase toda pergunta desta lista:

| Parâmetro | Valores |
|---|---|
| **Classe** | `Isolado` · `Extrato` · `Mevatyl` |
| **Canal** | `Varejo` (tudo que não é HOSPITALAR) · `Mercado Público` (HOSPITALAR) · os dois |
| **Período** | MAT (12 meses fechados), trimestre, mês, YTD |
| **Laboratório** | `EASE LABS` ou qualquer concorrente da `cddd.fab` |

Gabarito conferido no **AWS em 23/09/2026**, com **MAT Ago/26 = set/25 a ago/26** (`'202509'` a
`'202608'`). Os números mudam a cada carga; o que se avalia é o caminho e a ordem de grandeza.

---

## Bloco de classificação (base de quase todas as queries)

O mercado (`td.fato_td`) não tem coluna de classe: ela vem do nome da apresentação, na mesma regra
do Power BI. Este CTE é o cabeçalho reutilizável das queries abaixo.

```sql
-- CTE0 · Classificação de produto e canal (reutilizar em todas as perguntas de mercado)
WITH apres AS (
  SELECT f.cod_apresentacao,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO') AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END AS classe,
         CASE WHEN COALESCE(a.desc_apresentacao, ta.desc_apresentacao) = 'EXT DE CANNABIS ACH ACH 3676MG/ML GT-OR FR X 30ML N03A'
              THEN 36.76
              ELSE replace(COALESCE(NULLIF(regexp_replace(COALESCE(a.und_concentracao, ''), '[^0-9.,].*$', ''), ''),
                                    regexp_replace(COALESCE(a.desc_concentracao, ta.desc_concentracao, ''), '[^0-9.,].*$', '')), ',', '.')::numeric
         END AS conc,
         f.cod_subcanal, f.cod_anomes, f.cod_utc, f.und, f.valor_
  FROM td.fato_td f
  LEFT JOIN cddd.apres a ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta  ON ta.cod_apresentacao = f.cod_apresentacao   -- produtos novos ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb  ON fb.cod_fab = pr.cod_fab
),
mercado AS (
  SELECT ap.*, CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM apres ap LEFT JOIN cddd.canal dc ON dc.cod_subcanal = ap.cod_subcanal
)
SELECT 1;   -- as perguntas abaixo substituem esta linha final
```

- `und` e `valor_` vêm ×1000: divida por 1000.
- **Nunca** procure "ISOLADO" ou "EXTRATO" na descrição: essas palavras não existem lá.
- Os SKUs Ease: `234194` Isolado 100 mg/mL 30 mL · `254655` Isolado 100 mg/mL 10 mL ·
  `309653` Isolado 20 mg/mL 30 mL · `259434` Extrato 36,76 mg/mL 30 mL.

---

## P1 · Sell out e market share de uma classe inteira, por apresentação

*"Exporta as unidades vendidas de todos os produtos Isolados no MAT, com o market share."*
*Variações:* Extrato em vez de Isolado · só Varejo, só Mercado Público, ou os dois · trimestre ou ano.

**Confirmar antes:** classe, canal(is) e período. Se pedirem um MAT que ainda não fechou
(ex.: Out/26), avise e ofereça o último MAT disponível.

**Regras:** share da apresentação = unidades dela ÷ total da classe **no mesmo canal**; nunca
misture canais no denominador. Uma apresentação pode ter dois códigos e um nome comercial só.

```sql
-- CTE0 acima, depois:
SELECT desc_apres, laboratorio,
       SUM(und)/1000 AS unidades,
       ROUND(100*SUM(und)/SUM(SUM(und)) OVER (), 2) AS share_pct
FROM mercado
WHERE classe = 'Isolado'            -- ou 'Extrato'
  AND canal  = 'Varejo'             -- ou 'Mercado Público'; remova para os dois
  AND cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1, 2
ORDER BY unidades DESC;
```

**Gabarito (Isolado, Varejo, MAT Ago/26):** total **729.227** un. Líder: Prati-Donaduzzi VD 20 mg/mL
30 mL com 215.844 un. (29,60%); depois Mantecorp 23,75 10 mL (65.313) e Greencare 23,75 10 mL
(65.207). No Mercado Público o total é 121.112 un.

---

## P2 · Prescrição de uma classe inteira, por laboratório

*"Quantas prescrições os produtos Isolados tiveram no MAT? E cada laboratório?"*

**Confirmar antes:** molécula (Isolado = `CANABIDIOL`; Extrato = `EXTRATO CANNABIS SATIVA`) e período.

**Regras:** a prescrição **não separa por SKU**, só por molécula — não prometa abertura por
apresentação. O nome do laboratório está em `audit.laboratorio`; `audit.prescricao` traz só o código.

```sql
SELECT l.nome AS laboratorio,
       SUM(p.px1) AS px,
       ROUND((100*SUM(p.px1)/SUM(SUM(p.px1)) OVER ())::numeric, 2) AS share_px
FROM audit.prescricao p
JOIN audit.molecula_produto_relacao r
  ON r.cdgmarca = p.cdgmarca AND r.codigoconcentracao = p.cdgconcentracao
 AND r.codigoapresentacao = p.cdgapresentacao AND r.codigoforma = p.cdgforma::text
 AND r.cdglaboratorio = p.cdglaboratorio
LEFT JOIN audit.laboratorio l ON l.codigo = p.cdglaboratorio
WHERE r.descmole = 'CANABIDIOL'                       -- ou 'EXTRATO CANNABIS SATIVA'
  AND p.data BETWEEN '2025-09-01' AND '2026-08-01'    -- competências mensais
GROUP BY 1
ORDER BY px DESC;
```

**Gabarito (Canabidiol, MAT Ago/26):** Prati-Donaduzzi 165.560 PX (44,63%), Greencare 50.004
(13,48%), **Ease Labs 33.847 (9,12%)**, Mantecorp 33.311 (8,98%), Eurofarma 28.223 (7,61%).

---

## P3 · Market share por faixa de concentração

*"Em qual faixa de concentração a Ease é mais forte?"*

**Regras:** as faixas são as do Power BI (`CLASSNOME`). Faixa sem venda da Ease deve aparecer com
zero, não sumir da resposta.

```sql
-- CTE0 acima, depois:
SELECT classe,
       CASE WHEN classe='Isolado' AND conc <= 35  THEN 'Isolado até 35 mg/mL'
            WHEN classe='Isolado' AND conc <= 50  THEN 'Isolado até 50 mg/mL'
            WHEN classe='Isolado' AND conc <= 150 THEN 'Isolado 50 a 149 mg/mL'
            WHEN classe='Isolado'                 THEN 'Isolado acima 150 mg/mL'
            WHEN classe='Extrato' AND (conc < 80 OR conc = 200) THEN 'Extrato < 0,2% THC'
            WHEN classe='Extrato'                 THEN 'Extrato > 0,2% THC'
            ELSE 'Mevatyl' END AS faixa,
       SUM(und)/1000 AS un_mercado,
       COALESCE(SUM(und) FILTER (WHERE laboratorio='EASE LABS'), 0)/1000 AS un_ease,
       ROUND(100*COALESCE(SUM(und) FILTER (WHERE laboratorio='EASE LABS'),0)/NULLIF(SUM(und),0), 2) AS share_ease
FROM mercado
WHERE canal = 'Varejo' AND cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1, 2
ORDER BY un_mercado DESC;
```

**Gabarito (Varejo, MAT Ago/26):** a Ease tem **47,65%** da faixa "Isolado 50 a 149 mg/mL"
(43.078 de 90.401) e **18,36%** do "Extrato < 0,2% THC" (38.601 de 210.255), mas só **0,52%** da
maior faixa do mercado, "Isolado até 35 mg/mL" (537.341 un.). É a leitura que explica o share total.

---

## P4 · Evolução mensal do share dentro da classe

*"Como evoluiu o share da Ease nos Isolados nos últimos 12 meses?"*

**Regras:** share mês a mês, sempre dentro da mesma classe e canal. Aponte a tendência, não só os números.

```sql
-- CTE0 acima, depois:
SELECT cod_anomes,
       SUM(und)/1000 AS un_classe,
       SUM(und) FILTER (WHERE laboratorio='EASE LABS')/1000 AS un_ease,
       ROUND(100*SUM(und) FILTER (WHERE laboratorio='EASE LABS')/NULLIF(SUM(und),0), 2) AS share_pct
FROM mercado
WHERE classe='Isolado' AND canal='Varejo' AND cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1
ORDER BY 1;
```

**Gabarito:** share caiu de **6,85%** (set/25) para **5,80%** (ago/26), com piso de 5,67% em jun/26.
As unidades da Ease ficaram estáveis (3.5 a 4.0 mil/mês) enquanto o mercado cresceu de 57 mil para
67 mil — perda de share por crescimento do mercado, não por queda de volume.

---

## P5 · MAT contra MAT anterior

*"Crescemos ou perdemos espaço em relação ao MAT passado?"*

**Regras:** compare os dois MATs completos (24 meses no filtro) e separe o efeito volume do efeito
share.

```sql
-- CTE0 acima, depois:
SELECT CASE WHEN cod_anomes BETWEEN '202509' AND '202608' THEN 'MAT atual' ELSE 'MAT anterior' END AS periodo,
       SUM(und)/1000 AS un_classe,
       SUM(und) FILTER (WHERE laboratorio='EASE LABS')/1000 AS un_ease,
       ROUND(100*SUM(und) FILTER (WHERE laboratorio='EASE LABS')/NULLIF(SUM(und),0), 2) AS share_pct
FROM mercado
WHERE classe='Isolado' AND canal='Varejo' AND cod_anomes BETWEEN '202409' AND '202608'
GROUP BY 1
ORDER BY 1 DESC;
```

**Gabarito (Isolado, Varejo):** mercado 548.638 → **729.227** un. (+32,9%); Ease 39.944 → **45.867**
(+14,8%); share 7,28% → **6,29%**. A Ease cresceu, mas menos que o mercado.

---

## P6 · Ranking de laboratórios e posição da Ease

*"Em que posição estamos no mercado de Isolados?"*

```sql
-- CTE0 acima, depois:
SELECT laboratorio,
       SUM(und)/1000 AS unidades,
       ROUND(100*SUM(und)/SUM(SUM(und)) OVER (), 2) AS share_pct,
       RANK() OVER (ORDER BY SUM(und) DESC) AS posicao
FROM mercado
WHERE classe='Isolado' AND canal='Varejo' AND cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1
ORDER BY posicao;
```

**Gabarito:** 1º Prati-Donaduzzi 51,46%, 2º Greencare 11,09%, 3º Eurofarma 9,43%, 4º Mantecorp
9,38%, **5º Ease Labs 6,29%**, 6º Aché 5,24%.

---

## P7 · Share por UF (onde somos fortes e fracos)

*"Em quais estados temos mais share nos Isolados?"*

**Regras:** a UF vem do brick (`cddd.utc`), não do PDV — a `td.fato_td` não tem PDV. Corte UFs de
volume irrelevante antes de ranquear por share, senão um estado com 200 unidades lidera a lista.

```sql
-- CTE0 acima, depois:
SELECT u.uf,
       SUM(m.und)/1000 AS un_classe,
       SUM(m.und) FILTER (WHERE m.laboratorio='EASE LABS')/1000 AS un_ease,
       ROUND(100*SUM(m.und) FILTER (WHERE m.laboratorio='EASE LABS')/NULLIF(SUM(m.und),0), 2) AS share_pct
FROM mercado m
LEFT JOIN cddd.utc u ON u.cod_utc = m.cod_utc
WHERE m.classe='Isolado' AND m.canal='Varejo' AND m.cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1
HAVING SUM(m.und) > 1000000        -- ignora UF com menos de 1.000 unidades no período
ORDER BY share_pct DESC;
```

**Gabarito:** MG 10,48% (7.901 de 75.389), DF 9,21%, SE 8,21%, RJ 7,67%, RS 7,35% — todos acima da
média nacional de 6,29%.

---

## P8 · Comparação entre canais

*"Como fica Varejo contra Mercado Público no mesmo produto?"*

```sql
-- CTE0 acima, depois:
SELECT canal,
       SUM(und)/1000 AS un_classe,
       SUM(und) FILTER (WHERE laboratorio='EASE LABS')/1000 AS un_ease,
       ROUND(100*SUM(und) FILTER (WHERE laboratorio='EASE LABS')/NULLIF(SUM(und),0), 2) AS share_pct
FROM mercado
WHERE classe='Isolado' AND cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1;
```

**Gabarito:** Varejo 729.227 un. com 6,29% de share; Mercado Público 121.112 un. com **2,40%**. O
Mercado Público é 14% do volume da classe e a Ease é bem menos presente nele.

---

## P9 · Ticket médio de cada apresentação no período

*"Me dá a lista de todas as apresentações e o ticket médio de cada uma no período."*
*Variações:* só uma classe · só um canal · um laboratório específico · outro período.

**Confirmar antes:** período, canal e se quer todas as apresentações ou só de uma classe.

**Regras:**

- **Concorrentes:** ticket médio = `valor_ ÷ und` do painel (os dois ×1000, então a divisão dispensa
  o ajuste). É preço de mercado no canal, não preço de tabela.
- **Ease Labs: não use o preço do painel.** O ticket da Ease é definido pela empresa e entra fixo na
  query, por `cod_apresentacao`:

  | `cod_apresentacao` | EAN | Produto | Ticket |
  |---|---|---|---|
  | `234194` | 7896806601243 | Isolado 30 | R$ 799,00 |
  | `254655` | 7896806601281 | Isolado 10 | R$ 286,00 |
  | `259434` | 7896806601250 | Extrato | R$ 302,00 |
  | `309653` | 7896806601328 | Isolado 20 | R$ 174,30 |

- Apresentação da Ease **sem ticket mapeado** sai com o valor do painel e deve ser sinalizada — hoje
  é o caso da `CANNABIS SATIVA EAS EAS 79,14MG`, com 1 unidade no MAT. SKU novo da Ease sem ticket:
  avise, não invente preço.
- A lista traz **todas as apresentações com venda no recorte**, não só as de maior volume.

```sql
-- CTE0 acima, depois (o ticket da Ease é fixo; o dos concorrentes vem do painel):
, ticket_ease (cod_apresentacao, produto, preco) AS (
  VALUES (234194, 'Isolado 30', 799.00::numeric),
         (254655, 'Isolado 10', 286.00),
         (259434, 'Extrato',    302.00),
         (309653, 'Isolado 20', 174.30)
)
SELECT m.desc_apres            AS apresentacao,
       m.laboratorio,
       m.classe,
       m.cod_apresentacao,
       SUM(m.und)/1000         AS unidades,
       ROUND(CASE WHEN te.preco IS NOT NULL THEN te.preco
                  ELSE SUM(m.valor_)/NULLIF(SUM(m.und), 0) END::numeric, 2) AS ticket_medio,
       CASE WHEN te.preco IS NOT NULL THEN 'ticket Ease (fixo)'
            ELSE 'painel (valor_/und)' END AS origem
FROM mercado m
LEFT JOIN ticket_ease te ON te.cod_apresentacao = m.cod_apresentacao
WHERE m.canal = 'Varejo'                        -- ou 'Mercado Público'; remova para os dois
  AND m.cod_anomes BETWEEN '202509' AND '202608'
  -- AND m.classe = 'Isolado'                   -- opcional: uma classe só
GROUP BY 1, 2, 3, 4, te.preco
ORDER BY unidades DESC;                         -- ou ORDER BY ticket_medio DESC
```

**Gabarito (Varejo, MAT Ago/26):** **58 apresentações**. Ease com ticket fixo: Extrato R$ 302,00
(38.601 un.), Isolado 30 R$ 799,00 (26.083), Isolado 10 R$ 286,00 (16.994) e Isolado 20 R$ 174,30
(2.789). Nos concorrentes: Prati VD 20 mg/mL 30 mL R$ 182,93 (215.844 un.), Prati VD 20 mg/mL 10 mL
R$ 60,63 — o menor da lista —, Mantecorp 23,75 10 mL R$ 137,93 e Greencare 23,75 10 mL R$ 140,36.
O maior ticket do mercado é o Mevatyl, R$ 3.150,23.

Deixe claro na resposta que o ticket da Ease é preço interno e o dos concorrentes é preço de
mercado do painel: são naturezas diferentes na mesma coluna.

---

## P10 · Cobertura de bricks (onde o mercado vende e a Ease não)

*"Em quantos bricks o mercado vende Isolado e em quantos nós vendemos?"*

**Regras:** o cálculo é por brick (`cod_utc`), porque o mercado não tem PDV. "Não vendeu" aqui é
ausência de venda no período, não ausência de cadastro.

```sql
-- CTE0 acima, depois:
SELECT COUNT(*) FILTER (WHERE un_mercado > 0) AS bricks_com_mercado,
       COUNT(*) FILTER (WHERE un_ease > 0)    AS bricks_com_ease,
       ROUND(100.0*COUNT(*) FILTER (WHERE un_ease > 0)/NULLIF(COUNT(*) FILTER (WHERE un_mercado > 0),0), 1) AS cobertura_pct
FROM (
  SELECT cod_utc,
         SUM(und) AS un_mercado,
         SUM(und) FILTER (WHERE laboratorio='EASE LABS') AS un_ease
  FROM mercado
  WHERE classe='Isolado' AND canal='Varejo' AND cod_anomes BETWEEN '202509' AND '202608'
  GROUP BY 1) x;
```

**Gabarito:** o mercado vendeu Isolado em **16.918 bricks** e a Ease em **5.714** — cobertura de
**33,8%**. Para listar os bricks sem Ease, troque o `SELECT` externo por um filtro
`WHERE un_mercado > 0 AND COALESCE(un_ease,0) = 0` e junte com `cddd.utc` e `cddd.forca_vendas`.

---

## P11 · Unidades por prescrição (conversão)

*"Quantas unidades saem por prescrição?"*

**Regras:** cruza duas bases de natureza diferente — prescrição (`audit`, mensal, painel médico) e
sell out (`cddd.vw_sell_out`). É um indicador de proporção, não uma rastreabilidade receita a receita;
diga isso na resposta. Use o mesmo período nos dois lados.

```sql
WITH px AS (
  SELECT SUM(p.px1) AS px
  FROM audit.prescricao p
  JOIN audit.molecula_produto_relacao r
    ON r.cdgmarca = p.cdgmarca AND r.codigoconcentracao = p.cdgconcentracao
   AND r.codigoapresentacao = p.cdgapresentacao AND r.codigoforma = p.cdgforma::text
   AND r.cdglaboratorio = p.cdglaboratorio
  WHERE r.descmole = 'CANABIDIOL' AND p.cdglaboratorio = 'EAS'
    AND p.data BETWEEN '2025-09-01' AND '2026-08-01'
),
un AS (
  SELECT SUM(s.cdd + s.extras + s.mp + s.ss - s.pbm) AS unidades
  FROM cddd.vw_sell_out s
  WHERE s.cod_apres IN (234194, 254655, 309653)      -- Isolados Ease
    AND s.date >= '2025-09-01' AND s.date < '2026-09-01'
)
SELECT px.px, ROUND(un.unidades::numeric, 0) AS unidades,
       ROUND((un.unidades/NULLIF(px.px,0))::numeric, 2) AS unidades_por_px
FROM px, un;
```

**Gabarito (Isolados Ease, MAT Ago/26):** 33.847 PX e 48.265 unidades = **1,43 unidade por
prescrição**.

---

## P12 · Quem mais cresceu dentro da classe

*"Quais produtos mais cresceram no último MAT?"*

**Regras:** compare os dois MATs e **corte a base pequena** — produto que saiu de 3 para 60 unidades
cresce 1.900% e não diz nada. Produto que não existia no MAT anterior é lançamento: trate à parte,
sem calcular variação percentual.

```sql
-- CTE0 acima, depois:
SELECT desc_apres,
       SUM(und) FILTER (WHERE cod_anomes BETWEEN '202509' AND '202608')/1000 AS mat_atual,
       SUM(und) FILTER (WHERE cod_anomes BETWEEN '202409' AND '202508')/1000 AS mat_anterior,
       ROUND(100.0*(SUM(und) FILTER (WHERE cod_anomes BETWEEN '202509' AND '202608')
                  - SUM(und) FILTER (WHERE cod_anomes BETWEEN '202409' AND '202508'))
             /NULLIF(SUM(und) FILTER (WHERE cod_anomes BETWEEN '202409' AND '202508'),0), 1) AS var_pct
FROM mercado
WHERE classe='Isolado' AND canal='Varejo' AND cod_anomes BETWEEN '202409' AND '202608'
GROUP BY 1
HAVING SUM(und) FILTER (WHERE cod_anomes BETWEEN '202409' AND '202508') > 5000000   -- base mínima
ORDER BY var_pct DESC;
```

**Gabarito:** Eurofarma 20 mg/mL 30 mL +443,9% (8.892 → 48.360), Prati VD 20 mg/mL 10 mL +99,5%,
Aché 100 mg/mL 30 mL +85,1%, União Química 34,36 +75,5%, Aché 100 mg/mL 10 mL +67,3%.

---

## Nomes comerciais na resposta

A descrição do banco (`CANABIDIOL P.D P.D SOL VD 20MG/ML SL-OR FR X 30ML + 2 SER N03A`) não é o nome
que a diretoria usa (`Prati Donaduzzi VD CBD 20 mg/mL - 30mL`). Quando a entrega for para
apresentação, aplique o de-para do Power BI. Dois pontos:

- alguns pares de descrições viram o mesmo nome comercial e devem **somar numa linha só**
  (ex.: `CANNABIS SATIVA EAS EAS 79,14MG` entra em `Ease Labs CBD 100 mg/mL - 30 mL`);
- produtos novos ainda não têm nome comercial (hoje: 4 da Life Science, 1 Biolab 10 mL e 2 da
  Makrofarma) — mantenha a descrição original e sinalize.
