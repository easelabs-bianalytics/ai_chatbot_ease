# Referência de consultas — Chatbot BI Ease Labs

Banco: Amazon RDS for PostgreSQL 16.13. Colunas em maiúsculas exigem aspas (`"STATUS_TRN"`).

---

## 1. Auditoria e Prescrição Médica

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `audit.medico` | Cadastro de médicos do mercado | `cdgmedico`, `crm` (`MG0039273`), `nome`, `espec1`, `cidade`, `utc_codigo` (brick), `cep` |
| `audit.prescricao` | PX mensal por médico × produto × laboratório | `cdgmedico`, `cdglaboratorio` (Ease = `'EAS'`), `px1` (volume), `data` (competência, dia 1) |
| `audit.molecula_produto_relacao` | Produto → molécula | `descmole`: `'EXTRATO CANNABIS SATIVA'` ou `'CANABIDIOL'` |

- UF do médico = `left(crm, 2)`. `cdgregiao` não é UF.
- Prescrição separa só Extrato × Canabidiol, não por SKU.

```sql
-- Q01 · PX Ease de um médico por mês e molécula
SELECT p.data AS competencia, r.descmole, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
JOIN audit.molecula_produto_relacao r
  ON r.cdgmarca = p.cdgmarca AND r.codigoconcentracao = p.cdgconcentracao
 AND r.codigoapresentacao = p.cdgapresentacao AND r.codigoforma = p.cdgforma::text
 AND r.cdglaboratorio = p.cdglaboratorio
WHERE m.crm = :crm AND p.cdglaboratorio = 'EAS' AND p.px1 > 0
GROUP BY 1, 2
ORDER BY 1 DESC;
```

```sql
-- Q02 · Top prescritores Ease no período
SELECT m.crm, m.nome, m.espec1, m.cidade, left(m.crm, 2) AS uf, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
WHERE p.cdglaboratorio = 'EAS' AND p.px1 > 0
  AND p.data BETWEEN :data_ini AND :data_fim
GROUP BY 1, 2, 3, 4, 5
ORDER BY px DESC
LIMIT 50;
```

```sql
-- Q03 · Share Ease no mercado de cannabis por mês
SELECT p.data AS competencia,
       SUM(p.px1) FILTER (WHERE p.cdglaboratorio = 'EAS') AS px_ease,
       SUM(p.px1) AS px_mercado,
       ROUND((100.0 * SUM(p.px1) FILTER (WHERE p.cdglaboratorio = 'EAS') / NULLIF(SUM(p.px1), 0))::numeric, 2) AS share_pct
FROM audit.prescricao p
WHERE p.data BETWEEN :data_ini AND :data_fim
GROUP BY 1
ORDER BY 1;
```

```sql
-- Q04 · Prescritores Ease de um brick
SELECT m.crm, m.nome, m.espec1, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
WHERE p.cdglaboratorio = 'EAS' AND p.px1 > 0
  AND p.data BETWEEN :data_ini AND :data_fim
  AND m.utc_codigo = :cod_utc
GROUP BY 1, 2, 3
ORDER BY px DESC;
```

---

## 2. Sell Out e Dispensação de Unidades

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `cddd.vendas_consolidado` | Sell-out Ease por dia × PDV × SKU, já tratado | `cod_anomes` (dia), `cod_pdv`, `cod_apresentacao`, `desc_apresentacao`, `und`, `valor`, `cod_utc`, `cod_territorio`, `cod_ct`, `cod_gr` |
| `cddd.vw_sellout_mensal` | Sell-out total mensal por SKU (CDD + extras + MP + SS − PBM) | `ano_mes`, `cod_apresentacao`, `qtd`, `"QTD_LM"`, `"Cresc_%"` (razão) |
| `cddd.pdvs` | Cadastro de PDV | `cod_pdv` (bigint), `cnpj_pdv`, `desc_pdv`, `cidade`, `uf`, `cod_utc` |

- Use a `vendas_consolidado`, não a `cddd.fato_cdd` (ela já divide por 1000, exclui hospitalar, devolução e informantes duplicados).
- SKUs: `259434` Extrato · `234194` Isolado 30 mL · `254655` Isolado 10 mL · `309653` Isolado 20 mg.
- "Últimos N dias" conta a partir de `MAX(cod_anomes)`.

```sql
-- Q10 · Sell-out total mensal por SKU
SELECT ano_mes, cod_apresentacao, desc_apresentacao, qtd, "QTD_LM"
FROM cddd.vw_sellout_mensal
WHERE ano_mes BETWEEN :data_ini AND :data_fim
ORDER BY ano_mes DESC, cod_apresentacao;
```

```sql
-- Q11 · Sell-out de um PDV (CNPJ) por mês e SKU
SELECT date_trunc('month', v.cod_anomes)::date AS mes, v.desc_apresentacao, SUM(v.und) AS unidades
FROM cddd.vendas_consolidado v
JOIN cddd.pdvs p ON p.cod_pdv = v.cod_pdv::bigint
WHERE lpad(regexp_replace(p.cnpj_pdv, '\D', '', 'g'), 14, '0') = :cnpj
  AND v.cod_anomes BETWEEN :data_ini AND :data_fim
GROUP BY 1, 2
ORDER BY 1 DESC;
```

```sql
-- Q12 · Ranking de PDVs por sell-out
SELECT p.cnpj_pdv, p.desc_pdv, p.cidade, p.uf, SUM(v.und) AS unidades
FROM cddd.vendas_consolidado v
JOIN cddd.pdvs p ON p.cod_pdv = v.cod_pdv::bigint
WHERE v.cod_anomes BETWEEN :data_ini AND :data_fim
  AND v.cod_apresentacao = '259434'
GROUP BY 1, 2, 3, 4
ORDER BY unidades DESC
LIMIT 50;
```

```sql
-- Q13 · Sell-out por território, CT e GR
SELECT v.cod_territorio, fv.desc_territorio, ct.nome_abreviado_ct AS ct, gr.nome_gr AS gr, SUM(v.und) AS unidades
FROM cddd.vendas_consolidado v
LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
       ON fv.cod_territorio = v.cod_territorio::text
LEFT JOIN cddd.dim_ct ct ON ct.cod_ct = v.cod_ct
LEFT JOIN cddd.dim_gr gr ON gr.cod_gr = v.cod_gr
WHERE v.cod_anomes BETWEEN :data_ini AND :data_fim
GROUP BY 1, 2, 3, 4
ORDER BY unidades DESC;
```

```sql
-- Q14 · Sell-out dos últimos 90 dias de um brick
SELECT p.desc_pdv, v.desc_apresentacao, SUM(v.und) AS unidades
FROM cddd.vendas_consolidado v
JOIN cddd.pdvs p ON p.cod_pdv = v.cod_pdv::bigint
WHERE v.cod_utc = :cod_utc
  AND v.cod_anomes >= (SELECT MAX(cod_anomes) FROM cddd.vendas_consolidado) - INTERVAL '90 days'
GROUP BY 1, 2
ORDER BY unidades DESC;
```

---

## 3. Estoque nas Redes

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `estoque_redes.vw_estoque_cd_recente` | Snapshot mais recente de estoque de cada rede (10 redes) | `rede`, `cnpj`, `desc_loja`, `tipo` (`'PDV'`/`'CD'`), `cod_ean`, `estoque_qtde`, `data_recebimento` |
| `estoque_redes.vw_forecast_projecao_cd_extrato` | Projeção de ruptura de Extrato nos CDs | `rede`, `cd`, `estoque`, `dde_base`, `compra_arredondada`, `em_ruptura`, `dia` (0 = hoje) |
| `ruptura_extrato.vw_app_pdvs` | Lojas com Extrato em estoque, com coordenadas | `loja`, `rede`, `endereco`, `cidade`, `uf`, `estoque_un`, `latitude`, `longitude` |
| `ruptura_extrato.dim_cep_geo` | CEP → coordenada | `cep` (8 dígitos), `lat_ok`, `lon_ok` |

- Filtre `tipo = 'PDV'` para estoque de loja.
- EANs: `7896806601250` Extrato · `7896806601243` Isolado 30 mL · `7896806601281` Isolado 10 mL · `7896806601328` Isolado 20 mg.

```sql
-- Q20 · Estoque de uma loja por SKU
SELECT rede, desc_loja, cod_ean, estoque_qtde, data_recebimento
FROM estoque_redes.vw_estoque_cd_recente
WHERE tipo = 'PDV'
  AND lpad(regexp_replace(cnpj::text, '\D', '', 'g'), 14, '0') = :cnpj;
```

```sql
-- Q21 · Estoque por rede e SKU
SELECT rede, cod_ean, COUNT(DISTINCT cnpj) FILTER (WHERE estoque_qtde > 0) AS lojas_com_estoque,
       SUM(estoque_qtde) AS unidades, MAX(data_recebimento) AS data_estoque
FROM estoque_redes.vw_estoque_cd_recente
WHERE tipo = 'PDV'
GROUP BY 1, 2
ORDER BY 1, 2;
```

```sql
-- Q22 · Lojas com Extrato em estoque mais próximas de um CEP (linha reta)
WITH origem AS (
  SELECT lat_ok AS lat, lon_ok AS lon FROM ruptura_extrato.dim_cep_geo
  WHERE cep = lpad(regexp_replace(:cep, '\D', '', 'g'), 8, '0')
),
lojas AS MATERIALIZED (
  SELECT loja, rede, endereco, cidade, uf, telefone, estoque_un, latitude, longitude
  FROM ruptura_extrato.vw_app_pdvs WHERE latitude IS NOT NULL
)
SELECT l.loja, l.rede, l.endereco, l.cidade, l.uf, l.telefone, l.estoque_un,
       ROUND(ruptura_extrato.f_haversine_km(o.lat, o.lon, l.latitude, l.longitude)::numeric, 1) AS km
FROM lojas l CROSS JOIN origem o
WHERE ruptura_extrato.f_haversine_km(o.lat, o.lon, l.latitude, l.longitude) <= :raio_km
ORDER BY km
LIMIT 10;
```

```sql
-- Q23 · Ruptura de Extrato nos CDs hoje
SELECT rede, cd, estoque, dde_base, compra_arredondada, em_ruptura
FROM estoque_redes.vw_forecast_projecao_cd_extrato
WHERE dia = 0
ORDER BY em_ruptura DESC, dde_base;
```

---

## 4. PBM

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `pbm.fato_pbm_transacoes` | Transações do programa de benefício | `"STATUS_TRN"`, `"DATA_REF"`, `"EAN"`, `"MARCA"`, `"QTDE"` (texto), `"QTDE_DEVOLVIDA"` (texto), `"CNPJ_PDV"`, `"NOME_FANTASIA"`, `"UF_PROFISSIONAL"`, `"COD_PROFISSIONAL"`, `"NOME_PROFISSIONAL"` |

- Venda = `"STATUS_TRN" = 'CONFIRMADA'`.
- CRM = `"UF_PROFISSIONAL" || lpad("COD_PROFISSIONAL", 7, '0')`. `COD_PROFISSIONAL = '0'` = não informado.
- Não expor dados do consumidor (`CPF_CONS`, `NOME_CONS`, `E_MAIL`, `CELULAR`).

```sql
-- Q30 · Unidades PBM por mês e SKU
SELECT date_trunc('month', "DATA_REF")::date AS mes, "EAN",
       SUM("QTDE"::int - "QTDE_DEVOLVIDA"::int) AS unidades
FROM pbm.fato_pbm_transacoes
WHERE "STATUS_TRN" = 'CONFIRMADA' AND "DATA_REF" BETWEEN :data_ini AND :data_fim
GROUP BY 1, 2
ORDER BY 1 DESC;
```

```sql
-- Q31 · PDVs das transações PBM de um médico
SELECT "NOME_FANTASIA", "CNPJ_PDV", "CIDADE_PDV", "UF_PDV",
       SUM("QTDE"::int - "QTDE_DEVOLVIDA"::int) AS unidades, MAX("DATA_REF") AS ultima
FROM pbm.fato_pbm_transacoes
WHERE "STATUS_TRN" = 'CONFIRMADA'
  AND "UF_PROFISSIONAL" || lpad("COD_PROFISSIONAL", 7, '0') = :crm
GROUP BY 1, 2, 3, 4
ORDER BY unidades DESC
LIMIT 20;
```

```sql
-- Q32 · Médicos com mais unidades PBM
SELECT "UF_PROFISSIONAL" || lpad("COD_PROFISSIONAL", 7, '0') AS crm, MAX("NOME_PROFISSIONAL") AS nome,
       SUM("QTDE"::int - "QTDE_DEVOLVIDA"::int) AS unidades
FROM pbm.fato_pbm_transacoes
WHERE "STATUS_TRN" = 'CONFIRMADA' AND "COD_PROFISSIONAL" <> '0'
  AND "DATA_REF" BETWEEN :data_ini AND :data_fim
GROUP BY 1
ORDER BY unidades DESC
LIMIT 50;
```

---

## 5. Força de Vendas, Painel e Visitas

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `cddd.forca_vendas` | Brick → território → representante | `cod_utc` (bigint), `cod_territorio` (texto), `desc_territorio` |
| `cddd.scd_ct_territorio` + `cddd.dim_ct` | CT do território (vigente: `data_saida_territorio IS NULL`) | `cod_territorio`, `cod_ct`, `nome_abreviado_ct`, `email_ct` |
| `ruptura_extrato.vw_representantes_ativos` | Representantes ativos | `cod_territorio`, `desc_territorio`, `nome_abreviado_ct`, `email_ct` |
| `audit.rx_cadastro_mais_recente` | Painel atual de médicos por setor | `crm_link`, `nome`, `setor`, `setor_cliente` (= território), `categoria`, `classificacao`, `potencial`, `email`, `celular` |
| `audit.rx_visitas` | Histórico de visitas | `crm_norm`, `setor`, `data_da_visita`, `visita_efetiva` (`'S'`), `tipo_visita`, `comentarios` |

- `SEM REP` e `SETOR VAGO%` = território sem representante.

```sql
-- Q40 · Painel e representante de um médico
SELECT r.crm_link, r.nome, r.setor, fv.desc_territorio, ct.nome_abreviado_ct, ct.email_ct,
       r.categoria, r.classificacao, r.potencial
FROM audit.rx_cadastro_mais_recente r
LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
       ON fv.cod_territorio = r.setor_cliente
LEFT JOIN cddd.scd_ct_territorio s
       ON s.cod_territorio::text = r.setor_cliente AND s.data_saida_territorio IS NULL
LEFT JOIN cddd.dim_ct ct ON ct.cod_ct = s.cod_ct
WHERE r.crm_link = :crm;
```

```sql
-- Q41 · Representante de um PDV
SELECT p.cnpj_pdv, p.desc_pdv, p.cod_utc, fv.cod_territorio, fv.desc_territorio
FROM cddd.pdvs p
LEFT JOIN cddd.forca_vendas fv ON fv.cod_utc = p.cod_utc
WHERE lpad(regexp_replace(p.cnpj_pdv, '\D', '', 'g'), 14, '0') = :cnpj;
```

```sql
-- Q42 · Últimas visitas efetivas de um médico
SELECT data_da_visita::date, setor, tipo_visita, comentarios
FROM audit.rx_visitas
WHERE crm_norm = :crm AND visita_efetiva = 'S'
ORDER BY data_da_visita DESC
LIMIT 5;
```

```sql
-- Q43 · Painel de um setor com a última visita efetiva
SELECT r.crm_link, r.nome, r.categoria, r.potencial,
       MAX(v.data_da_visita)::date AS ultima_visita, COUNT(v.id_visita) AS visitas_efetivas
FROM audit.rx_cadastro_mais_recente r
LEFT JOIN audit.rx_visitas v
       ON v.crm_norm = r.crm_link AND v.setor = r.setor AND v.visita_efetiva = 'S'
WHERE r.setor = :setor
GROUP BY 1, 2, 3, 4
ORDER BY ultima_visita NULLS FIRST;
```

```sql
-- Q44 · Visitas efetivas por setor e mês
SELECT setor, date_trunc('month', data_da_visita)::date AS mes,
       COUNT(*) AS visitas, COUNT(DISTINCT crm_norm) AS medicos
FROM audit.rx_visitas
WHERE visita_efetiva = 'S' AND data_da_visita BETWEEN :data_ini AND :data_fim
GROUP BY 1, 2
ORDER BY 1, 2;
```

---

## 6. Mercado (TDD) e Cadastro de PDV

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `tdd.dim_pdv` | Cadastro de PDV do mercado | `"COD_PDV"`, `"CNPJ_PDV"` (bigint), `"DESC_PDV"`, `"CIDADE_PDV"`, `"UF_PDV"`, `"UTC_PDV"` |
| `tdd.fato_tdd` | Volume e categoria do PDV no mercado de cannabis | `"COD_PDV"`, `"COD_GRUPO"` (usar `3`), `"COD_PERIODO"` (`SEM01_202601`, `TRIM01_202506`…), `"CAT_UN_MERCADO"` (1 = maior, 8 = menor), `"UN_MERCADO"`, `"R$_PDV_MERCADO"` |
| `cddd.canal` | Subcanal → canal | `cod_subcanal`, `desc_subcanal`, `desc_canal`, `desc_grupo_canal` |

```sql
-- Q50 · Categoria e volume de mercado de um PDV
SELECT d."DESC_PDV", f."COD_PERIODO", f."CAT_UN_MERCADO", f."UN_MERCADO", f."R$_PDV_MERCADO"
FROM tdd.dim_pdv d
JOIN tdd.fato_tdd f ON f."COD_PDV" = d."COD_PDV"
WHERE d."CNPJ_PDV" = :cnpj::bigint AND f."COD_GRUPO" = 3
ORDER BY f."COD_PERIODO";
```

```sql
-- Q51 · Cadastro e canal de um PDV
SELECT p.cnpj_pdv, p.desc_pdv, p.desc_endereco, p.bairro, p.cidade, p.uf, p.cep, p.cod_utc,
       c.desc_subcanal, c.desc_canal
FROM cddd.pdvs p
LEFT JOIN cddd.canal c ON c.cod_subcanal = p.cod_subcanal
WHERE lpad(regexp_replace(p.cnpj_pdv, '\D', '', 'g'), 14, '0') = :cnpj;
```
