# IC — Índice de Conversão · referência para o chatbot

Complemento do [chatbot_bi_referencia_querys.md](chatbot_bi_referencia_querys.md). Tudo que a IA
precisa para responder qualquer pergunta sobre **IC**.

---

## 1. O que é o IC

**IC = share de sell out ÷ share de prescrição (PX)**, no mesmo período e no mesmo recorte.

É um índice criado pelo time de **BI & Analytics da Ease Labs** para medir quanto da prescrição
médica de um laboratório efetivamente vira venda no PDV. A prescrição diz o que o médico indicou; o
sell out diz o que saiu da farmácia. Quando um laboratório tem 10% da prescrição do mercado e apenas
7% da venda, algo se perdeu entre o consultório e o balcão — normalmente **troca de receituário na
ponta**: o paciente chega com a receita e sai com o produto de outro laboratório, por preço,
disponibilidade ou indicação do balconista.

| Faixa | Leitura |
|---|---|
| **IC ≈ 1** | A venda acompanha a prescrição: o que é receitado é o que sai |
| **IC < 1** | Perde-se venda no PDV. Quanto menor, maior a suspeita de troca no balcão, ruptura ou preço fora da faixa |
| **IC > 1** | Vende-se mais do que a prescrição observada explica: conversão forte no balcão, compra por indicação/recompra, ou prescrição subrepresentada no painel médico |

O IC **não prova** troca de receituário: ele aponta onde investigar. A conclusão vem do cruzamento
com estoque (ruptura), preço e cobertura de visita.

---

## 2. Regras de cálculo

| Lado | Fonte | Regras |
|---|---|---|
| **Sell out** | `td.fato_td` (mercado auditado) | `desc_canal <> 'HOSPITALAR'` · unidades ÷ 1000 · **exclui Mevatyl** |
| **Prescrição** | `audit.prescricao` (`px1`) | Competência mensal (dia 1) · **exclui Tetraidrocanabinol** |

- **O denominador é sempre o mercado no mesmo recorte.** IC de um representante usa o mercado do
  território dele, não o mercado nacional.
- **Laboratório:** no sell out vem de `cddd.fab.desc_sigla_fab`; na prescrição, de
  `audit.prescricao.cdglaboratorio`. As duas chaves são iguais (`EAS`, `ACH`, `GRE`, `MQF`, `P.D`,
  `EUF`, `U.Q`, `HBA`…), o que permite o cruzamento direto.
- **Classe** (quando a pergunta separar Extrato e Isolado):
  - sell out: `'EXT'` no nome da apresentação = Extrato, senão Isolado;
  - prescrição: `descmole = 'EXTRATO CANNABIS SATIVA'` = Extrato, `'CANABIDIOL'` = Isolado.
- **Período:** sempre mensal e igual dos dois lados. A prescrição fecha no dia 1 da competência, e o
  mercado (TD) fecha o mês inteiro: não compare um mês parcial de sell out com PX fechada.
- **Nunca use o sell out da Ease (`cddd.vw_sell_out` ou `fato_cdd`) no IC:** essas bases só têm a
  Ease e não produzem share de mercado.

---

## 3. Bloco base (reutilizar em todas as queries de IC)

```sql
-- CTE-IC · Prescrição e sell out prontos para qualquer recorte de IC
WITH mol AS (   -- 1 linha por chave de produto (a relação tem 1 chave duplicada)
  SELECT DISTINCT ON (cdgmarca, codigoconcentracao, codigoapresentacao, codigoforma, cdglaboratorio)
         cdgmarca, codigoconcentracao, codigoapresentacao, codigoforma, cdglaboratorio, descmole
  FROM audit.molecula_produto_relacao
  ORDER BY cdgmarca, codigoconcentracao, codigoapresentacao, codigoforma, cdglaboratorio, descmole
),
px AS (
  SELECT to_char(p.data, 'YYYYMM') AS mes,
         p.cdglaboratorio          AS lab,
         CASE WHEN r.descmole = 'EXTRATO CANNABIS SATIVA' THEN 'Extrato'
              WHEN r.descmole = 'CANABIDIOL'              THEN 'Isolado'
              ELSE 'Outros' END    AS classe,
         m.utc_codigo              AS cod_utc,     -- brick do médico
         p.px1                     AS px
  FROM audit.prescricao p
  LEFT JOIN mol r
         ON r.cdgmarca = p.cdgmarca AND r.codigoconcentracao = p.cdgconcentracao
        AND r.codigoapresentacao = p.cdgapresentacao AND r.codigoforma = p.cdgforma::text
        AND r.cdglaboratorio = p.cdglaboratorio
  LEFT JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
  WHERE p.data BETWEEN '2026-06-01' AND '2026-08-01'          -- competências
    AND (r.descmole IS NULL OR upper(r.descmole) NOT LIKE '%TETRAIDROCANABINOL%')
),
so AS (
  SELECT f.cod_anomes                              AS mes,
         COALESCE(fb.desc_sigla_fab, '??')         AS lab,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO') AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'
              THEN 'Extrato' ELSE 'Isolado' END    AS classe,
         f.cod_utc,                                          -- brick do PDV
         f.und / 1000.0                            AS und
  FROM td.fato_td f
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  WHERE dc.desc_canal <> 'HOSPITALAR'
    AND f.cod_anomes BETWEEN '202606' AND '202608'            -- mesmo período
    AND upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) NOT LIKE '%MEVATYL%'
)
SELECT 1;   -- as queries abaixo substituem esta linha
```

---

## 4. IC1 · IC de todos os laboratórios, mês a mês

*"Qual o IC de cada laboratório nos últimos meses?"* · *"Qual o IC da Ease?"* (filtrar `lab = 'EAS'`)

```sql
-- CTE-IC acima, depois:
, px_mes AS (SELECT mes, SUM(px)  AS px_mercado FROM px GROUP BY 1),
  so_mes AS (SELECT mes, SUM(und) AS so_mercado FROM so GROUP BY 1),
  px_lab AS (SELECT mes, lab, SUM(px)  AS px_lab FROM px GROUP BY 1, 2),
  so_lab AS (SELECT mes, lab, MAX(laboratorio) AS laboratorio, SUM(und) AS so_lab FROM so GROUP BY 1, 2)
SELECT s.mes,
       s.laboratorio,
       ROUND((100*p.px_lab/pm.px_mercado)::numeric, 2) AS share_px_pct,
       ROUND((100*s.so_lab/sm.so_mercado)::numeric, 2) AS share_sellout_pct,
       ROUND(((s.so_lab/sm.so_mercado) / NULLIF(p.px_lab/pm.px_mercado, 0))::numeric, 2) AS ic
FROM so_lab s
JOIN so_mes sm ON sm.mes = s.mes
JOIN px_lab p  ON p.mes = s.mes AND p.lab = s.lab
JOIN px_mes pm ON pm.mes = s.mes
WHERE s.so_lab > 500        -- corta laboratório sem volume: IC de base pequena oscila demais
ORDER BY s.mes, ic;
```

**Gabarito (jun a ago/26):** Ease Labs **0,73 · 0,70 · 0,76** — o pior entre os grandes. Aché 0,86 ·
0,86 · 0,88. Greencare 0,76 · 0,81 · 0,78. Do outro lado, Prati-Donaduzzi 1,24, Eurofarma 1,25 e
Herbarium 1,48 em jun/26: vendem acima da prescrição observada.

---

## 5. IC2 · IC por classe (Extrato e Isolado)

*"Qual o IC do nosso Extrato?"* · *"O IC é pior no Isolado ou no Extrato?"*

```sql
-- CTE-IC acima, depois:
, px_mes AS (SELECT mes, classe, SUM(px)  AS px_mercado FROM px WHERE classe <> 'Outros' GROUP BY 1, 2),
  so_mes AS (SELECT mes, classe, SUM(und) AS so_mercado FROM so GROUP BY 1, 2),
  px_lab AS (SELECT mes, classe, lab, SUM(px)  AS px_lab FROM px WHERE classe <> 'Outros' GROUP BY 1, 2, 3),
  so_lab AS (SELECT mes, classe, lab, MAX(laboratorio) AS laboratorio, SUM(und) AS so_lab FROM so GROUP BY 1, 2, 3)
SELECT s.mes, s.classe, s.laboratorio,
       ROUND((100*p.px_lab/pm.px_mercado)::numeric, 2) AS share_px_pct,
       ROUND((100*s.so_lab/sm.so_mercado)::numeric, 2) AS share_sellout_pct,
       ROUND(((s.so_lab/sm.so_mercado) / NULLIF(p.px_lab/pm.px_mercado, 0))::numeric, 2) AS ic
FROM so_lab s
JOIN so_mes sm ON sm.mes = s.mes AND sm.classe = s.classe
JOIN px_lab p  ON p.mes = s.mes AND p.classe = s.classe AND p.lab = s.lab
JOIN px_mes pm ON pm.mes = s.mes AND pm.classe = s.classe
WHERE s.classe = 'Isolado'          -- ou 'Extrato'; remova para os dois
  AND s.lab IN ('EAS', 'ACH', 'GRE')  -- remova para todos os laboratórios
ORDER BY s.classe, s.mes, ic;
```

**Gabarito (jun a ago/26):** o problema da Ease está no **Isolado** — IC 0,65 · 0,64 · 0,67, contra
**0,93 · 0,83 · 0,96 no Extrato**. No Extrato o Aché passa de 1 (1,17 · 1,11 · 1,24) e a Greencare
fica em 0,86 · 0,83 · 0,87.

---

## 6. IC3 · IC de um representante

*"Qual o IC da regional do Jonathan Abrahão?"*

O recorte é pelos **bricks do território**: a prescrição entra pelo brick do médico
(`audit.medico.utc_codigo`) e o sell out pelo brick do PDV (`td.fato_td.cod_utc`).

```sql
-- CTE-IC acima, depois:
, terr AS (
   SELECT cod_utc FROM cddd.forca_vendas
   WHERE desc_territorio ILIKE '%JONATHAN%'        -- só um pedaço do nome; confirme na E00
),
  px_f AS (SELECT * FROM px WHERE cod_utc IN (SELECT cod_utc FROM terr)),
  so_f AS (SELECT * FROM so WHERE cod_utc IN (SELECT cod_utc FROM terr)),
  px_mes AS (SELECT mes, SUM(px)  AS px_mercado FROM px_f GROUP BY 1),
  so_mes AS (SELECT mes, SUM(und) AS so_mercado FROM so_f GROUP BY 1),
  px_lab AS (SELECT mes, lab, SUM(px)  AS px_lab FROM px_f GROUP BY 1, 2),
  so_lab AS (SELECT mes, lab, MAX(laboratorio) AS laboratorio, SUM(und) AS so_lab FROM so_f GROUP BY 1, 2)
SELECT s.mes, s.laboratorio,
       ROUND((100*p.px_lab/pm.px_mercado)::numeric, 2) AS share_px_pct,
       ROUND((100*s.so_lab/sm.so_mercado)::numeric, 2) AS share_sellout_pct,
       ROUND(((s.so_lab/sm.so_mercado) / NULLIF(p.px_lab/pm.px_mercado, 0))::numeric, 2) AS ic,
       ROUND(s.so_lab::numeric, 0) AS unidades, ROUND(p.px_lab::numeric, 0) AS px
FROM so_lab s
JOIN so_mes sm ON sm.mes = s.mes
JOIN px_lab p  ON p.mes = s.mes AND p.lab = s.lab
JOIN px_mes pm ON pm.mes = s.mes
WHERE s.lab IN ('EAS', 'ACH', 'GRE', 'P.D')      -- ou só 'EAS'
ORDER BY s.mes, ic;
```

**Gabarito (Jonathan Abrahão, jun a ago/26):** IC da Ease **0,98 · 0,84 · 0,83** — bem acima da média
nacional dela, com 173, 176 e 181 unidades no território. No mesmo recorte, Prati-Donaduzzi fica em
1,09 a 1,12 e Greencare em 0,80 a 0,84.

---

## 7. IC4 · IC de um GR

*"Qual o IC da equipe do Gabriel Bastos?"*

Mesma lógica, subindo um nível na hierarquia: `fv_distrito` → `fv_territorio` → `forca_vendas`.

```sql
-- CTE-IC acima, depois:
, terr AS (
   SELECT fv.cod_utc
   FROM cddd.forca_vendas fv
   JOIN cddd.fv_territorio t ON t.cod_territorio = fv.cod_territorio
   JOIN cddd.fv_distrito d   ON d.cod_distrito = t.cod_distrito
   WHERE d.desc_distrito ILIKE '%GABRIEL%'
),
  px_f AS (SELECT * FROM px WHERE cod_utc IN (SELECT cod_utc FROM terr)),
  so_f AS (SELECT * FROM so WHERE cod_utc IN (SELECT cod_utc FROM terr)),
  px_mes AS (SELECT mes, SUM(px)  AS px_mercado FROM px_f GROUP BY 1),
  so_mes AS (SELECT mes, SUM(und) AS so_mercado FROM so_f GROUP BY 1),
  px_lab AS (SELECT mes, lab, SUM(px)  AS px_lab FROM px_f GROUP BY 1, 2),
  so_lab AS (SELECT mes, lab, MAX(laboratorio) AS laboratorio, SUM(und) AS so_lab FROM so_f GROUP BY 1, 2)
SELECT s.mes, s.laboratorio,
       ROUND((100*p.px_lab/pm.px_mercado)::numeric, 2) AS share_px_pct,
       ROUND((100*s.so_lab/sm.so_mercado)::numeric, 2) AS share_sellout_pct,
       ROUND(((s.so_lab/sm.so_mercado) / NULLIF(p.px_lab/pm.px_mercado, 0))::numeric, 2) AS ic
FROM so_lab s
JOIN so_mes sm ON sm.mes = s.mes
JOIN px_lab p  ON p.mes = s.mes AND p.lab = s.lab
JOIN px_mes pm ON pm.mes = s.mes
WHERE s.lab = 'EAS'
ORDER BY s.mes;
```

**Gabarito (GR Gabriel Bastos, Ease, jun a ago/26):** **0,78 · 0,76 · 0,81**, com share de PX de ~16%
e share de sell out de ~12% no distrito.

---

## 8. Outros recortes

A mesma estrutura serve para qualquer corte, trocando o filtro dos dois lados:

| Pergunta | O que muda |
|---|---|
| IC por UF ou região | Junte `cddd.utc` pelo `cod_utc` nos dois CTEs e agrupe por `uf`/`regiao` |
| IC de um brick | Filtre `cod_utc = :cod_utc` nos dois |
| IC acumulado (trimestre, MAT) | Tire o `mes` dos GROUP BY; some o período inteiro dos dois lados |
| IC de um SKU | **Não existe:** a prescrição não separa por apresentação, só por molécula |
| IC por PDV | **Não existe:** o mercado (TD) não tem PDV, só brick |

---

## 9. Armadilhas

- **Mês incompleto:** o mercado (TD) fecha o mês; se o último mês estiver parcial, o IC despenca sem
  significar nada. Use só meses fechados nos dois lados.
- **Base pequena:** laboratório, brick ou território com pouca venda gera IC instável. Corte por
  volume mínimo (ex.: `so_lab > 500`) e diga que cortou.
- **Recorte por território mistura dois bricks diferentes:** o do médico (prescrição) e o do PDV
  (venda). O paciente pode ser atendido num brick e comprar noutro, o que explica parte do IC alto ou
  baixo em territórios pequenos.
- **IC não é conversão individual:** não dá para dizer "de cada 10 receitas, 7 viraram venda". É
  proporção de participação de mercado entre duas bases distintas.
- **Não misture canais:** o IC oficial é sem hospitalar. Se alguém pedir com mercado público, diga
  que muda a régua e mostre os dois.
- **Sem THC e sem Mevatyl:** produtos à base de tetraidrocanabinol saem da prescrição e o Mevatyl sai
  do sell out, porque não têm equivalente do outro lado.
