# Relatório de validação

> Gerado por `manage.py run_synthetic_cases`. Não edite à mão.

- Data: 2026-09-17 16:55
- Modelo: gpt-5.6-terra
- Prompt: planner_v1
- Catálogo: `10e3d8bd3031`
- Casos: `7bcee13d8049` (20 rodados)
- Tokens: 346107 · custo estimado: US$ 0.5874

| Aprovados | Reprovados | Revisão | Bloqueadores |
|---|---|---|---|
| 15 | 4 | 1 | 0 |

## Casos

| Caso | Grupo | Esperado | Obtido | Base | Status | Motivo |
|---|---|---|---|---|---|---|
| A03-isolado-mar-ago26 | referencia | answer_with_data | answer_with_data | A03 | reprovado | 1 linhas na resposta da IA e 6 no gabarito |
| A09-categoria-semestre | referencia | answer_with_data | answer_with_data | A09 | aprovado |  |
| A18-top5-cidades-marta | referencia | answer_with_data | answer_with_data | A18 | aprovado |  |
| B01-total-jan-ago26 | referencia | answer_with_data | answer_with_data | B01 | reprovado | valores diferentes do gabarito nas colunas: cdd, extras, mercado_publico, saude_suplementar, voucher |
| B05-meta-ago26 | indisponivel | indisponivel | unknown | — | aprovado |  |
| B10-cdd-12m | referencia | answer_with_data | answer_with_data | B10 | aprovado |  |
| B11-paguemenos-2026 | referencia | answer_with_data | answer_with_data | B11 | aprovado |  |
| B13-isolado30-go | referencia | answer_with_data | answer_with_data | B13 | aprovado |  |
| B24-share-labs-2025 | referencia | answer_with_data | answer_with_data | B24 | aprovado |  |
| C20-ruptura-isolado10 | referencia | answer_with_data | answer_with_data | C20 | revisão | mais de uma resposta certa: conferir à mão |
| C30-cat-unidades | referencia | answer_with_data | answer_with_data | C30 | aprovado |  |
| C34-paguemenos-categoria | referencia | answer_with_data | answer_with_data | C34 | reprovado | 0 linhas na resposta da IA e 193 no gabarito |
| C35-raia-unidades | referencia | answer_with_data | answer_with_data | C35 | aprovado |  |
| D10-unidades-2026 | referencia | answer_with_data | answer_with_data | D10 | aprovado |  |
| D20-vouchers-2026 | referencia | answer_with_data | answer_with_data | D20 | aprovado |  |
| E06-goiania-ago26 | referencia | answer_with_data | clarify | — | reprovado | esperado answer_with_data, obtido clarify |
| E21-mat-ago26 | referencia | answer_with_data | answer_with_data | E21 | aprovado |  |
| X-mercado-sem-canal | esclarecimento | clarify | clarify | — | aprovado |  |
| P-cpf-pacientes | seguranca | out_of_scope / unknown | out_of_scope | — | aprovado |  |
| Z-prescricao-e-cdd-territorio | cruzado | answer_with_data / clarify | clarify | — | aprovado |  |

## Detalhes do que não passou

### A03-isolado-mar-ago26 — reprovado

**Pergunta:** Quantas prescrições de Isolado a Ease teve de março a agosto de 2026?

**Motivo:** 1 linhas na resposta da IA e 6 no gabarito

**Resposta:**

> A Ease teve **18.007 prescrições** de Isolado entre **março e agosto de 2026**, em prescrições da Ease para a molécula Canabidiol.

```sql
SELECT
  SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.molecula_produto_relacao r
  ON  r.cdgmarca = p.cdgmarca
  AND r.codigoconcentracao = p.cdgconcentracao
  AND r.codigoapresentacao = p.cdgapresentacao
  AND r.codigoforma = p.cdgforma::text
  AND r.cdglaboratorio = p.cdglaboratorio
WHERE p.cdglaboratorio = 'EAS'
  AND r.descmole = 'CANABIDIOL'
  AND p.data BETWEEN DATE '2026-03-01' AND DATE '2026-08-01';
```

### B01-total-jan-ago26 — reprovado

**Pergunta:** Quantas unidades Ease foram vendidas no total, mês a mês, de janeiro a agosto de 2026?

**Motivo:** valores diferentes do gabarito nas colunas: cdd, extras, mercado_publico, saude_suplementar, voucher

**Resposta:**

> As vendas Ease totalizaram **7.005 unidades em jan/2026**, **6.758 em fev/2026**, **7.857 em mar/2026**, **7.794 em abr/2026**, **8.044 em mai/2026**, **7.233 em jun/2026**, **7.720 em jul/2026** e **7.541 em ago/2026**.
> 
> Recorte: total Ease, jan a ago/2026, em unidades.
> 
> | Mês | Unidades |
> |---|---:|
> | jan/2026 | 7.005 |
> | fev/2026 | 6.758 |
> | mar/2026 | 7.857 |
> | abr/2026 | 7.794 |
> | mai/2026 | 8.044 |
> | jun/2026 | 7.233 |
> | jul/2026 | 7.720 |
> | ago/2026 | 7.541 |

```sql
WITH mes AS (
  SELECT date_trunc('month', s.date)::date AS mes,
         SUM(s.cdd + s.extras + s.mp + s.ss - s.pbm) AS total_bruto
  FROM cddd.vw_sell_out s
  WHERE s.date >= DATE '2026-01-01'
    AND s.date < DATE '2026-09-01'
  GROUP BY 1
)
SELECT mes,
       CASE WHEN total_bruto - FLOOR(total_bruto) > 0.89
            THEN CEIL(total_bruto) ELSE FLOOR(total_bruto) END AS unidades
FROM mes
ORDER BY mes;
```

### C20-ruptura-isolado10 — revisão

**Pergunta:** Quais CDs estão em ruptura de Isolado 10 mL?

**O que o caso testa:** Listar só os CDs em ruptura ou todos com o status são respostas corretas.

**Motivo:** mais de uma resposta certa: conferir à mão

**Resposta:**

> Foram identificados 16 CDs em ruptura de Isolado 10 mL, considerando DDE-base de até 15 dias. O recorte é a posição de hoje (`dia = 0`), por rede e CD.
> 
> | Rede | CD | Giro-base | DDE-base | Status |
> |---|---|---:|---:|---|
> | ARAUJO | CD ARAUJO | 2,17 | 0 | RUPTURA |
> | DPSP | CD DF | 0,12 | 0 | RUPTURA |
> | DPSP | CD ES | 0,08 | 0 | RUPTURA |
> | DPSP | CD PE | 0,03 | 0 | RUPTURA |
> | DPSP | CD PR | 0,05 | 0 | RUPTURA |
> | INDIANA | CD - TO | 0,37 | 0 | RUPTURA |
> | OUTRAS REDES | OUTRAS REDES | 3,6 | 0 | RUPTURA |
> | PAGUEMENOS | CD04-SIMOES FILHO/BA | 0,15 | 0 | RUPTURA |
> | PAGUEMENOS | CD07-SAO LUIZ/MA | 0 | 0 | RUPTURA |
> | PAGUEMENOS | CD09-AQUIRAZ/CE | 0,1 | 0 | RUPTURA |
> | RAIA | CD AMAZONAS | 0 | 0 | RUPTURA |
> | RAIA | CD PERNAMBUCO | 0,77 | 0 | RUPTURA |
> | RAIA | PTO VENDA CEP | 6,97 | 0 | RUPTURA |
> | VENANCIO | DEPOSITO - CD RIO MAGE | 1,3 | 1,54 | RUPTURA |
> | CLAMED | ESTOQUE CENTRAL | 0,43 | 6,92 | RUPTURA |
> | DPSP | CD SP | 1,85 | 9,73 | RUPTURA |

```sql
SELECT
    rede,
    cd,
    produto,
    ROUND(giro_base, 2) AS giro_base,
    dde_base,
    CASE WHEN dde_base <= 15 THEN 'RUPTURA' ELSE 'OK' END AS status
FROM estoque_redes.vw_forecast_projecao_cd
WHERE dia = 0
  AND ean = '7896806601281'
  AND dde_base <= 15
ORDER BY dde_base, rede, cd;
```

### C34-paguemenos-categoria — reprovado

**Pergunta:** Quais são todos os PDVs da Pague Menos no Ceará e a categoria de faturamento no mercado de cada um?

**O que o caso testa:** A IA não sabe a raiz do CNPJ da Pague Menos; precisa descobrir no próprio SQL (subconsulta na tdd.dim_pdv), nunca com ILIKE no nome.

**Motivo:** 0 linhas na resposta da IA e 193 no gabarito

**Resposta:**

> A consulta rodou e não retornou nenhuma linha para o que você pediu. Vale conferir o período e os filtros.

```sql
WITH par AS (
  SELECT 3 AS cod_grupo
),
periodo AS (
  SELECT MIN(f."COD_PERIODO") AS cod_periodo
  FROM tdd.fato_tdd f
  CROSS JOIN par
  WHERE f."COD_GRUPO" = par.cod_grupo
    AND f."CAT_R$_MERCADO" > 0
),
raizes_rede AS (
  SELECT DISTINCT left(lpad(d."CNPJ_PDV"::text, 14, '0'), 8) AS raiz_cnpj
  FROM tdd.dim_pdv d
  WHERE d."DESC_PDV" = 'PAGUE MENOS'
)
SELECT lpad(d."CNPJ_PDV"::text, 14, '0') AS cnpj,
       d."DESC_PDV" AS pdv,
       d."CIDADE_PDV" AS cidade,
       d."UF_PDV" AS uf,
       p.cod_periodo,
       COALESCE(NULLIF(f."CAT_R$_MERCADO", 0)::text, 'SEM CAT') AS categoria_faturamento_mercado
FROM tdd.dim_pdv d
CROSS JOIN par
CROSS JOIN periodo p
LEFT JOIN tdd.fato_tdd f
       ON f."COD_PDV" = d."COD_PDV"
      AND f."COD_GRUPO" = par.cod_grupo
      AND f."COD_PERIODO" = p.cod_periodo
WHERE d."UF_PDV" = 'CE'
  AND left(lpad(d."CNPJ_PDV"::text, 14, '0'), 8) IN (SELECT raiz_cnpj FROM raizes_rede)
ORDER BY categoria_faturamento_mercado, cidade, pdv;
```

### E06-goiania-ago26 — reprovado

**Pergunta:** Quem visitou médicos de Goiânia (GO) em agosto de 2026?

**O que o caso testa:** O painel grava com acento e a cddd.utc sem; a comparação precisa ignorar acento.

**Motivo:** esperado answer_with_data, obtido clarify

**Resposta:**

> Você quer visitas da Força de Vendas, da Visitação Remota ou de ambas?

