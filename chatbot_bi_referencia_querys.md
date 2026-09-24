# Referência de consultas — Chatbot BI Ease Labs

Banco: Amazon RDS for PostgreSQL 16.13. Colunas em maiúsculas exigem aspas (`"STATUS_TRN"`).

**As queries abaixo são referência, não resposta pronta.** A IA deve interpretar o que o usuário
pediu — período, recorte, granularidade, se é Ease ou mercado — e montar a melhor consulta para
aquele pedido, usando estas como ponto de partida.

**Se um schema, tabela ou coluna não existir no banco, não invente a resposta.** Não troque por
outra tabela parecida nem estime o número. Diga ao usuário, de forma cordial, que essa informação
ainda não está disponível na base e encerre o assunto. Exemplo: *"Ainda não tenho acesso à
informação de meta dos representantes na base. Posso ajudar com o resultado de vendas?"*

**As tabelas listadas são as principais de cada tema, não a lista completa.** Qualquer tabela ou
view dos schemas `audit`, `cddd`, `td`, `tdd`, `pbm` e `estoque_redes` pode ser usada
quando a pergunta exigir. Consulte `information_schema.columns` antes de usar uma tabela que não
esteja aqui.

**Resolva o nome antes de medir.** Nome próprio — pessoa, rede, cidade, produto, laboratório —
nunca entra na consulta inteiro. Busque por **um pedaço**: só o primeiro nome, ou só o sobrenome,
com `ILIKE '%pedaço%'`. As grafias divergem entre as fontes, e às vezes entre duas tabelas do
mesmo tema: o mesmo representante é `HERMES BIZZOTO` em `cddd.forca_vendas.desc_territorio` e
`Hermes Bizzotto` em `cddd.dim_ct.nome_abreviado_ct`. `ILIKE '%HERMES BIZOTTO%'`, do jeito que o
usuário escreveu, não acha nenhum dos dois. O mesmo vale para rede (`PAGUE MENOS` × `PAGUEMENOS`),
cidade (`cddd.utc.cidade` é sem acento) e produto. Se o pedaço trouxer mais de um, **mostre os que
encontrou e pergunte qual**; não escolha por conta própria.

**Nome de representante é `cddd.forca_vendas.desc_territorio`, e só ali.** Qualquer pergunta
"por representante" — venda, visita, prescrição, cobertura — traz o nome dessa coluna, ligada pelo
`cod_territorio` (texto na `forca_vendas`, inteiro na `vw_sell_out`: `s.cod_territorio::text`).
`nome_abreviado_ct` e `dim_ct` não são o nome do representante; a `dim_ct` serve para saber se ele
foi desligado.

**Nenhuma linha não é zero.** Consulta que volta vazia quase nunca significa "não houve venda":
na maioria das vezes o nome não casou, a pessoa não estava ativa no período, ou o período não tem
carga. Antes de concluir qualquer coisa, verifique — numa consulta de checagem, não no chute:

1. **o nome existe?** Refaça a busca com um pedaço menor, sem filtro de período, e veja o que
   existe de parecido.
2. **estava ativo no período?** `cddd.dim_ct.data_demissao` (desligamento) e
   `cddd.scd_ct_territorio.data_saida_territorio` (saída do território) dizem até quando. Atenção:
   `cddd.forca_vendas` é a **foto de hoje** — quem saiu não aparece nela de jeito nenhum, mesmo
   tendo vendido no passado.
3. **o período tem dado?** Veja qual foi o último mês com movimento para aquele recorte.

A resposta precisa dizer **o que aconteceu**: *"não encontrei esse representante; você quis dizer
Ricardo Bastos?"*, *"o Ricardo Reis foi desligado em 18/05/2026, então não há ago/26 para
comparar"*, *"esse mês ainda não tem carga"*. Nunca "a consulta não retornou nada".

## Quando não houver consulta exata: o raciocínio vale mais que a consulta

**Pergunta sem consulta pronta é o caso normal, não a exceção.** As referências abaixo ensinam
*padrões* (lista com share, ranking, evolução mensal, MAT contra MAT, recorte por UF...) e *regras*
de cada base. O usuário vai combinar um padrão de um tema com a medida de outro. Nunca responda
"não tenho essa consulta": monte a partir do que este documento ensina. Só diga que não dá quando
o **dado** não existir na base (regra acima).

**O fluxo, sempre nesta ordem:**

1. **Decomponha a pergunta** em medida (unidades, faturamento, PX, estoque, adesões, visitas),
   recorte (classe, produto, laboratório, canal, geografia, pessoa) e período.
2. **Escolha a base pela medida, não pelas palavras da pergunta:**

   | Medida pedida | Base | Seção |
   |---|---|---|
   | Prescrição (PX), médico, especialidade | `audit` | 1 |
   | Unidades e faturamento **da Ease** | `cddd` (sell out) | 2.1 e 2.2 |
   | Unidades e faturamento **do mercado**, share entre laboratórios | `td.fato_td` | 2.3 |
   | Estoque, ruptura, categoria de PDV | `estoque_redes` | 3 |
   | Adesão, transação, voucher | `pbm` | 4 |
   | Representante, painel, visita | `cddd` e `audit.rx_*` | 5 |

3. **Ache a referência mais parecida com o padrão**, mesmo que seja de outro tema, e copie a
   *forma* dela: janela de tempo, denominador do share, filtros, cortes de base mínima.
4. **Traduza cada conceito para a base escolhida.** O mesmo conceito tem nome e coluna diferentes
   em cada uma — é aqui que a maioria dos erros acontece:

   | Conceito | Mercado (`td`) | Prescrição (`audit`) | Sell out Ease (`cddd`) |
   |---|---|---|---|
   | Classe Isolado / Extrato | regra do nome da apresentação (2.3) | `molecula_produto_relacao.descmole` = `'CANABIDIOL'` / `'EXTRATO CANNABIS SATIVA'` | pelo SKU (`cod_apres`) |
   | Laboratório | `cddd.fab.desc_fab` (via `apres` → `prod`) | `audit.laboratorio.nome` (via `cdglaboratorio`, `'EAS'` = Ease) | só Ease |
   | Produto | apresentação: SKU com tamanho de frasco | `audit.produto.nome`: marca + concentração + forma, **sem tamanho de frasco** | SKU |
   | Canal Varejo × Mercado Público | `cddd.canal.desc_canal` (`HOSPITALAR` = Mercado Público) | **não existe** | colunas de fonte (`cdd`, `mp`, `extras`...) |
   | Geografia | brick `cod_utc` → `cddd.utc` | brick do médico `audit.medico.utc_codigo`; UF = `left(crm, 2)` | PDV |
   | Período | `cod_anomes`, texto `'YYYYMM'` | `data`, competência no dia 1 | `date` |

5. **Coluna que este documento não mostra:** confira em `information_schema.columns` antes de usar.
6. **Confira o resultado antes de responder:** o share soma 100% no denominador certo (mesma
   classe, mesmo canal)? O total bate com a ordem de grandeza de uma referência vizinha? Um número
   fora do esperado é sinal de filtro errado, não de descoberta.
7. **Diga na resposta o que você adaptou:** de qual referência partiu, o período usado e os limites
   da base (ex.: "a prescrição não separa por frasco", "a auditoria não tem canal").

**Exemplo.** *"Me dá a lista dos produtos Isolados com a prescrição e o share de PX no MAT."* Não há
consulta pronta — a B33 faz isso no mercado, não na prescrição. O caminho:

- a medida é PX → base `audit`, seção 1. A referência de partida é a **A19** (PX de uma molécula
  por laboratório); o padrão "lista da classe com share" vem da **B33**;
- "Isolado" na auditoria é `descmole = 'CANABIDIOL'`, e não a regra do nome, que é do mercado;
- "produto" é `audit.produto.nome`, ligado à prescrição pela mesma chave composta da
  `molecula_produto_relacao`. Troque o agrupamento da A19 de laboratório para produto; o share
  continua `SUM(SUM(p.px1)) OVER ()`;
- avise dois limites: a prescrição abre por concentração e forma, **não por frasco** (o Isolado
  100 mg/mL da Ease de 10 e de 30 mL é uma linha só), e não existe Varejo × Mercado Público na
  auditoria;
- confira: MAT set/25–ago/26 dá 34 produtos e 370,9 mil PX; Prati VD 20 mg/mL lidera (33,27%) e o
  Ease 100 mg/mL é o 4º (8,49%). O total bate com a soma da A19.

**Períodos.** MAT = os 12 meses fechados até o último mês com carga (`MAT Ago/26` = set/25 a
ago/26). Pedido de MAT que ainda não fechou: use o último MAT completo e diga qual período usou e
por quê. Trimestre, mês e YTD seguem a mesma lógica: nunca complete meses que não têm carga.

---

## 1. Auditoria e Prescrição Médica

**Toda pergunta sobre prescrição médica é respondida no schema `audit`.**

**Para qualquer output quantitativo, pergunte antes o período da análise** (mês, trimestre, ano,
intervalo). Só siga sem perguntar se o usuário já tiver dito o período.

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `audit.medico` | Cadastro de médicos do mercado | `cdgmedico`, `crm` (`MG0039273`), `nome`, `espec1`, `cidade`, `utc_codigo` (brick) |
| `audit.prescricao` | PX mensal por médico × produto × laboratório | `cdgmedico`, `cdglaboratorio`, `px1`, `data` (competência, dia 1), `cdgespecialidade` |
| `audit.laboratorio` | Código → nome do laboratório (`EAS` = EASE LABS) | `codigo`, `nome` |
| `audit.produto` | Produtos do mercado | `cdgmarca`, `cdgconcentracao`, `cdgapresentacao`, `cdgforma`, `nome`, `cdglaboratorio` |
| `audit.especialidade` | Código → nome da especialidade | `codigo`, `nome` |
| `audit.molecula_produto_relacao` | Produto → molécula | `descmole`: `'EXTRATO CANNABIS SATIVA'` ou `'CANABIDIOL'` |
| `audit.rx_cadastro_mais_recente` | Painel atual: médicos visitados por setor | `crm_link`, `nome`, `setor`, `setor_cliente` (território), `frequencia`, `dias_sem_visita`, `categoria`, `potencial` |
| `audit.rx_visitas` | Histórico de visitas | `crm_norm`, `setor`, `data_da_visita`, `visita_efetiva` (`'S'`), `tipo_visita`, `comentarios` |

- `audit.prescricao` liga com `audit.produto` e com `audit.molecula_produto_relacao` por **chave
  composta**: `cdgmarca` + `cdgconcentracao` + `cdgapresentacao` + `cdgforma` (+ `cdglaboratorio`).
  `cdgforma` é bigint na prescrição e texto nas outras duas: use `p.cdgforma::text`.
- UF do médico = `left(crm, 2)`. `cdgregiao` não é UF.

### Prescrição — volume

*"Quantas prescrições o mercado teve por mês?" / "E só a Ease?"*

```sql
-- A01 · Prescrição do mercado por mês
SELECT
  p.data,
  SUM(p.px1) AS px
FROM audit.prescricao p
-- WHERE p.cdglaboratorio = 'EAS'      -- descomente para só Ease
GROUP BY 1
ORDER BY 1 DESC;
```

*"Como está a prescrição de cada produto Ease mês a mês?"*

```sql
-- A02 · Prescrição por produto, mês a mês
SELECT
  p.data,
  pr.nome AS produto,
  SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.produto pr
  ON  pr.cdgmarca        = p.cdgmarca
  AND pr.cdgconcentracao = p.cdgconcentracao
  AND pr.cdgapresentacao = p.cdgapresentacao
  AND pr.cdgforma        = p.cdgforma::text
  AND pr.cdglaboratorio  = p.cdglaboratorio
WHERE p.cdglaboratorio = 'EAS'         -- troque o laboratório aqui
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

*"Quantas prescrições de Extrato tivemos nos últimos meses?"*

```sql
-- A03 · Prescrição só do Extrato (troque para 'CANABIDIOL' se for Isolado)
SELECT
  p.data,
  SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.molecula_produto_relacao r
  ON  r.cdgmarca           = p.cdgmarca
  AND r.codigoconcentracao = p.cdgconcentracao
  AND r.codigoapresentacao = p.cdgapresentacao
  AND r.codigoforma        = p.cdgforma::text
  AND r.cdglaboratorio     = p.cdglaboratorio
WHERE p.cdglaboratorio = 'EAS'
  AND r.descmole = 'EXTRATO CANNABIS SATIVA'
GROUP BY 1
ORDER BY 1 DESC;
```

*"Qual o share da Ease no mercado?"*

```sql
-- A04 · Share Ease no mercado de cannabis por mês
SELECT p.data AS competencia,
       SUM(p.px1) FILTER (WHERE p.cdglaboratorio = 'EAS') AS px_ease,
       SUM(p.px1) AS px_mercado,
       ROUND((100.0 * SUM(p.px1) FILTER (WHERE p.cdglaboratorio = 'EAS') / NULLIF(SUM(p.px1), 0))::numeric, 2) AS share_pct
FROM audit.prescricao p
WHERE p.data BETWEEN :data_ini AND :data_fim
GROUP BY 1
ORDER BY 1;
```

*"Quais médicos prescrevem Ease no brick X?"*

```sql
-- A05 · Prescritores Ease de um brick
SELECT m.crm, m.nome, m.espec1, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
WHERE p.cdglaboratorio = 'EAS' AND p.px1 > 0
  AND p.data BETWEEN :data_ini AND :data_fim
  AND m.utc_codigo = :cod_utc
GROUP BY 1, 2, 3
ORDER BY px DESC;
```

*"Quais as prescrições da neurologia?"*

```sql
-- A06 · Prescrição por especialidade
SELECT p.data, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.especialidade e ON e.codigo = p.cdgespecialidade
WHERE e.nome = :especialidade          -- ex.: 'NEUROLOGIA', 'PSIQUIATRIA'
  AND p.cdglaboratorio = 'EAS'
GROUP BY 1
ORDER BY 1 DESC;
```

*"Quantos médicos prescrevem Ease?"*

```sql
-- A07 · Médicos prescritores por mês (troque o laboratório para comparar com concorrente)
SELECT p.data, COUNT(DISTINCT p.cdgmedico) AS medicos_prescritores
FROM audit.prescricao p
WHERE p.cdglaboratorio = 'EAS'         -- troque o laboratório aqui
  AND p.px1 > 0
GROUP BY 1
ORDER BY 1 DESC;
```

*"Qual o RX per capita?"*

```sql
-- A08 · RX per capita (PX ÷ médicos prescritores)
SELECT p.data,
       SUM(p.px1) AS px,
       COUNT(DISTINCT p.cdgmedico) AS medicos,
       ROUND((SUM(p.px1) / NULLIF(COUNT(DISTINCT p.cdgmedico), 0))::numeric, 1) AS rx_per_capita
FROM audit.prescricao p
WHERE p.cdglaboratorio = 'EAS' AND p.px1 > 0
GROUP BY 1
ORDER BY 1 DESC;
```

### Categoria do médico

**Sempre pergunte de qual período é a categoria.** Se o usuário não disser, ofereça os períodos
já calculados no banco:

| View | Período | Base |
|---|---|---|
| `audit.vw_cat_ult_trim_movel` | Último trimestre móvel | Mercado |
| `audit.vw_cat_ult_quad_movel` | Último quadrimestre móvel (já traz `crm`) | Mercado |
| `audit.vw_cat_ult_quad_movel_ease` | Último quadrimestre móvel | **Só Ease** |
| `audit.vw_cat_ult_sem_movel` | Último semestre móvel | Mercado |
| `audit.vw_cat_ult_sem_movel_ease` | Último semestre móvel | **Só Ease** |
| `audit.vw_cat_ytd`, `vw_cat_anual`, `vw_cat_mat_2023/2024/2025`, `vw_cat_s1_2025`, `vw_cat_s2_2025`, `vw_cat_trim_movel_hist`, `vw_cat_ult_quad_movel_hist` | YTD, ano fechado, MAT e históricos mês a mês | Mercado |

Todas têm `cdgmedico`, `categoria` (1 = maior prescritor, 5 = menor) e o volume de PX do período.
**Se o usuário pedir um período que não existe nessas views, monte a query de categoria direto na
`audit.prescricao`.**

**SEM CAT:** médico que não aparece na view de categoria do período é **SEM CAT**. Parta sempre do
cadastro (`audit.medico` ou do painel) com `LEFT JOIN` na view e use
`COALESCE(categoria::text, 'SEM CAT')`. Nunca descarte esses médicos das contagens.

*"Qual a categoria do médico X no último trimestre?"*

```sql
-- A09 · Categoria de um médico (troque a view conforme o período pedido)
SELECT m.crm,
       m.nome,
       COALESCE(c.categoria::text, 'SEM CAT') AS categoria,
       c.px_3m
FROM audit.medico m
LEFT JOIN audit.vw_cat_ult_trim_movel c ON c.cdgmedico = m.cdgmedico
WHERE m.crm = :crm;
-- Sem linha = CRM não encontrado no cadastro. Com linha e 'SEM CAT' = médico sem categoria no período.
```

*"Como evoluiu a prescrição mensal dos médicos categoria 1 a 3 do último trimestre móvel?"*

```sql
-- A10 · Evolução mensal de PX dos médicos categoria 1 a 3
SELECT p.data,
       COUNT(DISTINCT p.cdgmedico) AS medicos,
       SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.vw_cat_ult_trim_movel c ON c.cdgmedico = p.cdgmedico
WHERE c.categoria BETWEEN 1 AND 3
  AND p.cdglaboratorio = 'EAS'
  AND p.data BETWEEN :data_ini AND :data_fim
GROUP BY 1
ORDER BY 1 DESC;
```

### Médico, painel e representante

O representante do médico sai de `audit.rx_cadastro_mais_recente.setor_cliente` →
`cddd.forca_vendas.cod_territorio`; o nome está em `desc_territorio`. O usuário escreve o nome de
várias formas ("Hermes", "Hermes Amorim", "Hermes Bizotto") e todas apontam para o mesmo
`desc_territorio`. Busque por `ILIKE '%primeiro nome%'` e, se voltar mais de um, pergunte qual.

*"O médico X está sendo visitado?"*

```sql
-- A11 · Médico está no painel hoje, com qual frequência e há quanto tempo sem visita
SELECT r.crm_link, r.nome, r.setor, r.setor_cliente, r.frequencia, r.freq_numerica,
       r.dias_sem_visita, r.categoria, r.potencial, r.classificacao
FROM audit.rx_cadastro_mais_recente r
WHERE r.crm_link = :crm;
-- Sem linha = não está em nenhum painel atual.
```

*"Quais as últimas visitas do painel do setor 1111?"*

```sql
-- A12 · Últimas visitas efetivas do painel de um setor
SELECT v.crm_norm, v.nome, MAX(v.data_da_visita)::date AS ultima_visita, COUNT(*) AS visitas
FROM audit.rx_visitas v
WHERE v.setor = 1111                   -- troque o setor conforme o representante
  AND v.visita_efetiva = 'S'
GROUP BY 1, 2
ORDER BY ultima_visita DESC
LIMIT 100;
```

*"Qual o setor do Hermes?"*

```sql
-- A13 · Território e código do representante pelo nome
SELECT DISTINCT f.cod_territorio, f.desc_territorio
FROM cddd.forca_vendas f
WHERE f.desc_territorio ILIKE '%' || :rep || '%';
```

**Quando pedirem "as prescrições do representante", confirme o que ele quer:** as prescrições do
**painel** dele (médicos que ele visita, via `rx_cadastro_mais_recente`) ou as do **território**
dele (todos os médicos dos bricks dele, via `cddd.forca_vendas.cod_utc` → `audit.medico.utc_codigo`).
São números diferentes.

```sql
-- A14 · PX do PAINEL do representante
SELECT p.data, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
WHERE m.crm IN (
        SELECT r.crm_link FROM audit.rx_cadastro_mais_recente r
        WHERE r.setor_cliente IN (SELECT DISTINCT cod_territorio FROM cddd.forca_vendas
                                  WHERE desc_territorio ILIKE '%' || :rep || '%'))
  AND p.cdglaboratorio = 'EAS'
GROUP BY 1
ORDER BY 1 DESC;
```

```sql
-- A15 · PX do TERRITÓRIO do representante (todos os bricks dele)
SELECT p.data, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
WHERE m.utc_codigo IN (SELECT cod_utc FROM cddd.forca_vendas
                       WHERE desc_territorio ILIKE '%' || :rep || '%')
  AND p.cdglaboratorio = 'EAS'
GROUP BY 1
ORDER BY 1 DESC;
```

**Pediram as duas** ("do painel e do território", "painel e região"): uma consulta só, com
as duas visões rotuladas e **nunca somadas** — o painel está dentro do território. Hermes,
ago/26: 157 PX no painel e 307 no território.

```sql
-- A21 · PX do PAINEL e do TERRITÓRIO do representante, lado a lado
SELECT 'Painel' AS visao, p.data, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
WHERE m.crm IN (
        SELECT r.crm_link FROM audit.rx_cadastro_mais_recente r
        WHERE r.setor_cliente IN (SELECT DISTINCT cod_territorio FROM cddd.forca_vendas
                                  WHERE desc_territorio ILIKE '%' || :rep || '%'))
  AND p.cdglaboratorio = 'EAS'
GROUP BY 1, 2
UNION ALL
SELECT 'Território (bricks)' AS visao, p.data, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
WHERE m.utc_codigo IN (SELECT cod_utc FROM cddd.forca_vendas
                       WHERE desc_territorio ILIKE '%' || :rep || '%')
  AND p.cdglaboratorio = 'EAS'
GROUP BY 1, 2
ORDER BY 1, 2 DESC;
```

### Gerente regional (GR)

GR é o líder dos representantes. Hierarquia: `cddd.fv_distrito` (`desc_distrito` = nome do GR) →
`cddd.fv_territorio` (por `cod_distrito`) → `cddd.forca_vendas` (por `cod_territorio`).

*"Como evoluiu a prescrição mensal dos médicos categoria 1 a 3 do painel do Gabriel Bastos?"*

```sql
-- A16 · PX mensal dos médicos categoria 1 a 3 do painel de um GR
WITH territorios AS (
  SELECT t.cod_territorio
  FROM cddd.fv_territorio t
  JOIN cddd.fv_distrito d ON d.cod_distrito = t.cod_distrito
  WHERE d.desc_distrito ILIKE '%' || :gr || '%'
),
painel AS (
  SELECT DISTINCT r.crm_link
  FROM audit.rx_cadastro_mais_recente r
  WHERE r.setor_cliente IN (SELECT cod_territorio FROM territorios)
)
SELECT p.data, COUNT(DISTINCT p.cdgmedico) AS medicos, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
JOIN audit.vw_cat_ult_trim_movel c ON c.cdgmedico = m.cdgmedico
WHERE m.crm IN (SELECT crm_link FROM painel)
  AND c.categoria BETWEEN 1 AND 3
  AND p.cdglaboratorio = 'EAS'
  AND p.data BETWEEN :data_ini AND :data_fim
GROUP BY 1
ORDER BY 1 DESC;
```

### Geolocalização da prescrição

`cddd.utc` traz cidade, UF e região de cada brick (`cod_utc`, `desc_utc`, `cidade`, `uf`, `regiao`).
Ligue com o médico (`audit.medico.utc_codigo`) ou com o representante (`cddd.forca_vendas.cod_utc`).

*"Em quais cidades estão as prescrições?"*

```sql
-- A17 · PX por brick, cidade e UF
SELECT u.cod_utc, u.desc_utc, u.cidade, u.uf, u.regiao, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
JOIN cddd.utc u ON u.cod_utc = m.utc_codigo
WHERE p.cdglaboratorio = 'EAS'
  AND p.data BETWEEN :data_ini AND :data_fim
GROUP BY 1, 2, 3, 4, 5
ORDER BY px DESC
LIMIT 50;
```

*"Quais as 10 cidades com mais PX Ease no território do Hermes no último trimestre?"*

```sql
-- A18 · Top 10 cidades em PX Ease no território de um representante, último trimestre
SELECT u.cidade, u.uf, SUM(p.px1) AS px
FROM audit.prescricao p
JOIN audit.medico m ON m.cdgmedico = p.cdgmedico
JOIN cddd.utc u     ON u.cod_utc = m.utc_codigo
WHERE p.cdglaboratorio = 'EAS'
  AND m.utc_codigo IN (SELECT cod_utc FROM cddd.forca_vendas
                       WHERE desc_territorio ILIKE '%HERMES%')      -- troque o representante aqui
  AND p.data > (SELECT MAX(data) - INTERVAL '3 months' FROM audit.prescricao)   -- 3 últimas competências
GROUP BY 1, 2
ORDER BY px DESC
LIMIT 10;
```

"Último trimestre" = as 3 competências mais recentes da base. A query usa o **território** do
representante (bricks dele); para o **painel**, troque o filtro pelo da A14.

### Prescrição de uma classe inteira (molécula)

*"Quantas prescrições os produtos Isolados tiveram no MAT? E cada laboratório?"*

- Classe na auditoria = molécula: Isolado = `CANABIDIOL`; Extrato = `EXTRATO CANNABIS SATIVA`.
- A prescrição **não separa por SKU nem por frasco**: separa por produto (marca + concentração +
  forma). Não prometa abertura por apresentação.
- O nome do laboratório está em `audit.laboratorio`; `audit.prescricao` traz só o código.
- Para a lista **por produto**, troque o agrupamento para `audit.produto.nome` (exemplo no início
  deste documento).

```sql
-- A19 · Prescrição de uma molécula (classe) por laboratório, com share de PX
SELECT l.nome AS laboratorio,
       SUM(p.px1) AS px,
       ROUND((100*SUM(p.px1)/SUM(SUM(p.px1)) OVER ())::numeric, 2) AS share_px
FROM audit.prescricao p
JOIN audit.molecula_produto_relacao r
  ON r.cdgmarca = p.cdgmarca AND r.codigoconcentracao = p.cdgconcentracao
 AND r.codigoapresentacao = p.cdgapresentacao AND r.codigoforma = p.cdgforma::text
 AND r.cdglaboratorio = p.cdglaboratorio
LEFT JOIN audit.laboratorio l ON l.codigo = p.cdglaboratorio
WHERE r.descmole = 'CANABIDIOL'                       -- Isolado; Extrato = 'EXTRATO CANNABIS SATIVA'
  AND p.data BETWEEN '2025-09-01' AND '2026-08-01'    -- competências mensais (dia 1)
GROUP BY 1
ORDER BY px DESC;
```

Conferido no RDS em 23/09/2026 (Canabidiol, MAT set/25–ago/26): Prati-Donaduzzi 165.560 PX
(44,63%), Greencare 50.004 (13,48%), **Ease Labs 33.847 (9,12%)**, Mantecorp 33.311 (8,98%),
Eurofarma 28.223 (7,61%).

### Unidades por prescrição (conversão)

*"Quantas unidades saem por prescrição?"*

Cruza duas bases de natureza diferente: prescrição (`audit`, mensal, painel médico) e sell out
(`cddd.vw_sell_out`). É um indicador de **proporção**, não rastreabilidade receita a receita — diga
isso na resposta. Use o mesmo período nos dois lados e a mesma classe (Isolados Ease = SKUs
`234194`, `254655`, `309653`; Extrato Ease = `259434` com `descmole = 'EXTRATO CANNABIS SATIVA'`).

```sql
-- A20 · Unidades vendidas por prescrição (conversão PX → sell out Ease)
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
       ROUND((un.unidades/NULLIF(px.px, 0))::numeric, 2) AS unidades_por_px
FROM px, un;
```

Conferido no RDS em 23/09/2026 (Isolados Ease, MAT set/25–ago/26): 33.847 PX e 48.265 unidades =
**1,43 unidade por prescrição**.

---

## 2. Sell Out e Dispensação de Unidades

O Sell Out tem três cenários. **Identifique qual deles o usuário quer antes de montar a query.**

| Cenário | Pergunta típica | Fonte principal |
|---|---|---|
| **2.1 Sell Out Ease Total** | "Quantas unidades a Ease vendeu no mês?", "Quanto vendeu o representante X?", "Bateu a meta?" | `cddd.vw_sell_out` |
| **2.2 Sell Out Ease PDVs (CDD)** | "Quantas unidades a Raia dispensou?", "Quanto vendeu o PDV X?" | `cddd.fato_cdd` |
| **2.3 Sell Out Mercado (TD)** | "Qual o faturamento do mercado?", "Qual o market share por laboratório?" | `td.fato_td` |

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `cddd.vw_sell_out` | Unidades Ease totais por dia × CT × SKU | `date`, `cod_ct`, `nome_abreviado_ct`, `cod_gr`, `cod_territorio`, `cod_apres`, `cdd`, `extras`, `mp`, `ss`, `pbm` (Voucher) |
| `cddd.fato_cdd` | Dispensação Ease por dia × PDV × SKU × informante | `cod_anomes` (date), `cod_pdv` (texto), `cod_apresentacao` (texto), `cod_informante`, `cod_tipo_transacao`, `und` (×1000) |
| `td.fato_td` | Mercado de cannabis por mês × brick × SKU × subcanal | `cod_anomes` (texto `'YYYYMM'`), `cod_apresentacao`, `cod_subcanal`, `cod_utc`, `und` (×1000), `valor_` (×1000) |
| `cddd.apres` | SKU → marca | `cod_apresentacao`, `desc_apresentacao`, `cod_marca`, `ean` |
| `cddd.prod` / `cddd.fab` | Marca → laboratório | `prod.cod_marca`, `prod.cod_fab` → `fab.cod_fab`, `fab.desc_fab`, `fab.desc_sigla_fab` (`'EAS'`) |
| `cddd.pdvs` | Cadastro de PDV | `cod_pdv` (bigint), `cnpj_pdv`, `desc_pdv`, `cidade`, `uf`, `cod_utc`, `cod_subcanal` |
| `cddd.informantes` | Origem do dado de dispensação e rede | `cod_informante`, `desc_informante`, `desc_grupo_informante` (rede) |
| `cddd.canal` | Subcanal → canal | `cod_subcanal`, `desc_canal` (`FARMACIAS`, `HOSPITALAR`, `OUTROS`) |
| `cddd.dim_ct` / `cddd.dim_gr` | Nome do representante (CT) e do gerente regional (GR) | `cod_ct`, `nome_abreviado_ct`, `data_demissao` (desligamento) / `cod_gr`, `nome_gr` |
| `cddd.forca_vendas` / `cddd.fv_territorio` / `cddd.fv_distrito` | Brick → território → GR | `cod_utc`, `cod_territorio`, `desc_territorio`, `cod_distrito`, `desc_distrito` |
| `cddd.vendas_extras` | Fonte das vendas extras | `data_venda`, `cod_territorio`, `produto`, `cod_produto`, `qtd`, `deleted_at` |
| `cddd.venda_mercado_publico` | Fonte de Mercado Público e Saúde Suplementar | `data_venda`, `modalidade`, `produto`, `frascos`, `total_sell_out`, `ct`, `uf`, `orgao`, `deleted_at` |
| `remuneracao_fv.fato_remuneracao` ⚠️ | Meta mensal de cada representante (**ainda não disponível no banco AWS**) | `mes`, `cod_ct`, `nome_representante`, `setor`, `nivel`, `fat_base`, `fat_alvo_bonus` (meta), `cod_gr` |

- `und` da `cddd.fato_cdd` e `und`/`valor_` da `td.fato_td` vêm multiplicados por 1000: divida por 1000.
- Ticket médio para converter unidades Ease em faturamento: `259434` Extrato **R$ 302,00** · `234194` Isolado 30 mL **R$ 799,30** · `309653` Isolado 20 mg **R$ 174,30** · `254655` Isolado 10 mL **R$ 286,00**.

### 2.1 Sell Out Ease Total

Unidades Ease vendidas pela companhia, somando todos os canais. É o número da força de vendas.

**Total = `cdd + extras + mp + ss − pbm`** (CDD + vendas extras + Mercado Público + Saúde
Suplementar − Voucher). Arredondamento: se a parte decimal for **maior que 0,89**, arredonda para
cima; senão, para baixo.

*"Quantas unidades Ease foram dispensadas mês a mês?"*

```sql
-- B01 · Sell Out Ease Total mês a mês, com cada componente
WITH mes AS (
  SELECT date_trunc('month', s.date)::date AS mes,
         SUM(s.cdd)    AS cdd,
         SUM(s.extras) AS extras,
         SUM(s.mp)     AS mercado_publico,
         SUM(s.ss)     AS saude_suplementar,
         SUM(s.pbm)    AS voucher,
         SUM(s.cdd + s.extras + s.mp + s.ss - s.pbm) AS total_bruto
  FROM cddd.vw_sell_out s
  GROUP BY 1
)
SELECT mes, cdd, extras, mercado_publico, saude_suplementar, voucher,
       CASE WHEN total_bruto - FLOOR(total_bruto) > 0.89
            THEN CEIL(total_bruto) ELSE FLOOR(total_bruto) END AS total
FROM mes
ORDER BY mes DESC;
```

*"Quantas unidades vendeu cada representante em julho?"*

```sql
-- B02 · Sell Out Ease Total por representante
WITH nomes AS (
  -- o nome do representante é o da forca_vendas (desc_territorio), e só ele
  SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas
),
rep AS (
  SELECT COALESCE(n.desc_territorio, 'SEM TERRITÓRIO ATUAL') AS representante,
         SUM(s.cdd + s.extras + s.mp + s.ss - s.pbm) AS total_bruto
  FROM cddd.vw_sell_out s
  LEFT JOIN nomes n ON n.cod_territorio = s.cod_territorio::text   -- texto × inteiro
  WHERE s.date >= :data_ini AND s.date < :data_fim    -- data_fim = 1º dia do mês seguinte
  -- AND n.desc_territorio ILIKE '%' || :rep || '%'    -- um representante específico
  GROUP BY 1
)
SELECT representante,
       CASE WHEN total_bruto - FLOOR(total_bruto) > 0.89
            THEN CEIL(total_bruto) ELSE FLOOR(total_bruto) END AS unidades
FROM rep
ORDER BY unidades DESC;
```

*"Quantas unidades vendeu a equipe de cada GR?"*

```sql
-- B03 · Sell Out Ease Total por GR (cod_gr dos CTs que venderam no mês)
WITH gr AS (
  SELECT g.nome_gr AS gr,
         SUM(s.cdd + s.extras + s.mp + s.ss - s.pbm) AS total_bruto
  FROM cddd.vw_sell_out s
  LEFT JOIN cddd.dim_gr g ON g.cod_gr = s.cod_gr
  WHERE s.date >= :data_ini AND s.date < :data_fim
  GROUP BY 1
)
SELECT gr,
       CASE WHEN total_bruto - FLOOR(total_bruto) > 0.89
            THEN CEIL(total_bruto) ELSE FLOOR(total_bruto) END AS unidades
FROM gr
ORDER BY unidades DESC;
```

`cddd.dim_gr.nome_gr` traz só o primeiro nome (`Gabriel`); o nome completo está em
`cddd.fv_distrito.desc_distrito` (`GABRIEL BASTOS`).

*"Quanto a Ease faturou por produto mês a mês?"*

```sql
-- B04 · Faturamento Ease Total por SKU (unidades × ticket médio)
SELECT date_trunc('month', s.date)::date AS mes,
       s.cod_apres,
       SUM(s.cdd + s.extras + s.mp + s.ss - s.pbm) AS unidades,
       ROUND((SUM(s.cdd + s.extras + s.mp + s.ss - s.pbm) *
             CASE s.cod_apres WHEN 259434 THEN 302.00
                              WHEN 234194 THEN 799.30
                              WHEN 309653 THEN 174.30
                              WHEN 254655 THEN 286.00 END)::numeric, 2) AS faturamento
FROM cddd.vw_sell_out s
WHERE s.date >= :data_ini AND s.date < :data_fim
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

#### Mês atual contra o mesmo período do mês anterior

*"Como estão as vendas deste mês, comparado ao mesmo período do mês anterior?"*

- **Data de corte = último dia com CDD**, a fonte que chega todo dia.
- **Mesmo período = do dia 1 ao mesmo dia** do mês anterior, nunca o mês inteiro (31/03 vira o
  último dia de fevereiro).
- **Mesmas fontes dos dois lados.** Extras, Mercado Público e Saúde Suplementar chegam depois do
  mês: a que ainda não tem dado no mês atual sai também do anterior. Diga na resposta quais ficaram
  de fora (`fontes_fora`), e que o número não é o sell out total do mês.
  O Voucher é **descontado** (`− pbm`), e a resposta diz isso.
- **Isso é o padrão, não uma proibição.** Se o usuário pedir para incluir as fontes ("considere
  Extras, Mercado Público e Saúde Suplementar também"), some **todas as fontes nos dois períodos**
  e traga **cada componente por período** (`cdd`, `extras`, `mp`, `ss`, `voucher` e o total, uma
  linha por período — B43). É o que mostra que a fonte do mês atual está zerada por falta de carga,
  enquanto o mês anterior a tem — e por isso a variação do total não é comparável. Repetir a B17
  e devolver o mesmo número foi o erro de 23/09/2026.
- Por representante: some a mesma lógica agrupando pelo nome da `forca_vendas` (B02).

```sql
-- B17 · Mês atual até a data de corte contra o mesmo período do mês anterior
WITH corte AS (
  -- o último dia com CDD é a data de corte: é a fonte que chega todo dia
  SELECT MAX(date) AS d FROM cddd.vw_sell_out WHERE cdd > 0
),
periodos AS (
  SELECT d,
         date_trunc('month', d)::date                          AS ini_atual,
         (date_trunc('month', d) - INTERVAL '1 month')::date   AS ini_anterior,
         -- mesmo dia do mês anterior; 31/03 vira 28 ou 29/02, sem invadir março
         LEAST((date_trunc('month', d) - INTERVAL '1 month')::date + (d - date_trunc('month', d)::date),
               date_trunc('month', d)::date - 1)               AS fim_anterior
  FROM corte
),
base AS (
  SELECT CASE WHEN s.date >= p.ini_atual THEN 'atual' ELSE 'anterior' END AS periodo,
         SUM(s.cdd) AS cdd, SUM(s.extras) AS extras, SUM(s.mp) AS mp, SUM(s.ss) AS ss, SUM(s.pbm) AS pbm
  FROM cddd.vw_sell_out s
  CROSS JOIN periodos p
  WHERE s.date BETWEEN p.ini_atual AND p.d
     OR s.date BETWEEN p.ini_anterior AND p.fim_anterior
  GROUP BY 1
),
fontes AS (
  -- fonte que ainda não chegou no mês atual sai dos DOIS lados
  SELECT COALESCE(MAX(extras) FILTER (WHERE periodo = 'atual'), 0) > 0 AS tem_extras,
         COALESCE(MAX(mp)     FILTER (WHERE periodo = 'atual'), 0) > 0 AS tem_mp,
         COALESCE(MAX(ss)     FILTER (WHERE periodo = 'atual'), 0) > 0 AS tem_ss
  FROM base
),
comparavel AS (
  SELECT b.periodo,
         b.cdd + CASE WHEN f.tem_extras THEN b.extras ELSE 0 END
               + CASE WHEN f.tem_mp     THEN b.mp     ELSE 0 END
               + CASE WHEN f.tem_ss     THEN b.ss     ELSE 0 END
               - b.pbm AS bruto
  FROM base b CROSS JOIN fontes f
)
SELECT p.ini_atual, p.d AS data_corte, p.ini_anterior, p.fim_anterior,
       ROUND(MAX(c.bruto) FILTER (WHERE c.periodo = 'atual')) AS unidades_atual,
       ROUND(MAX(c.bruto) FILTER (WHERE c.periodo = 'anterior')) AS unidades_anterior,
       ROUND(MAX(c.bruto) FILTER (WHERE c.periodo = 'atual') - MAX(c.bruto) FILTER (WHERE c.periodo = 'anterior')) AS variacao,
       ROUND((100 * (MAX(c.bruto) FILTER (WHERE c.periodo = 'atual') - MAX(c.bruto) FILTER (WHERE c.periodo = 'anterior'))
             / NULLIF(MAX(c.bruto) FILTER (WHERE c.periodo = 'anterior'), 0))::numeric, 1) AS variacao_pct,
       concat_ws(', ', 'CDD', CASE WHEN f.tem_extras THEN 'extras' END,
                 CASE WHEN f.tem_mp THEN 'Mercado Público' END, CASE WHEN f.tem_ss THEN 'Saúde Suplementar' END) AS fontes_comparadas,
       concat_ws(', ', CASE WHEN NOT f.tem_extras THEN 'extras' END,
                 CASE WHEN NOT f.tem_mp THEN 'Mercado Público' END, CASE WHEN NOT f.tem_ss THEN 'Saúde Suplementar' END) AS fontes_fora
FROM periodos p CROSS JOIN fontes f CROSS JOIN comparavel c
GROUP BY p.ini_atual, p.d, p.ini_anterior, p.fim_anterior, f.tem_extras, f.tem_mp, f.tem_ss;
```

Conferido no RDS em 23/09/2026: corte em **20/09**, só o CDD já chegou em setembro; **4.306**
unidades (1–20/09) contra **4.716** (1–20/08), **−8,7%**. Comparar com agosto inteiro dava −43%.

*"Considere Extras, Mercado Público, Saúde Suplementar e Voucher também"* — o mesmo comparativo, com **todas as
fontes nos dois períodos**, componente a componente:

```sql
-- B43 · Mês atual contra o mesmo período do mês anterior, com TODAS as fontes, componente a componente
WITH corte AS (
  SELECT MAX(date) AS d FROM cddd.vw_sell_out WHERE cdd > 0
),
periodos AS (
  SELECT d,
         date_trunc('month', d)::date                          AS ini_atual,
         (date_trunc('month', d) - INTERVAL '1 month')::date   AS ini_anterior,
         LEAST((date_trunc('month', d) - INTERVAL '1 month')::date + (d - date_trunc('month', d)::date),
               date_trunc('month', d)::date - 1)               AS fim_anterior
  FROM corte
),
por_periodo AS (
  SELECT CASE WHEN s.date >= p.ini_atual THEN 'atual' ELSE 'anterior' END AS periodo,
         MIN(s.date) AS de, MAX(s.date) AS ate,
         SUM(s.cdd) AS cdd, SUM(s.extras) AS extras, SUM(s.mp) AS mp, SUM(s.ss) AS ss, SUM(s.pbm) AS pbm,
         SUM(s.cdd + s.extras + s.mp + s.ss - s.pbm) AS todas,
         SUM(s.cdd - s.pbm)                          AS so_cdd
  FROM cddd.vw_sell_out s
  CROSS JOIN periodos p
  WHERE s.date BETWEEN p.ini_atual AND p.d
     OR s.date BETWEEN p.ini_anterior AND p.fim_anterior
  GROUP BY 1
)
-- uma linha por período, com cada componente; a variação vem calculada nas duas linhas
SELECT periodo, de, ate,
       ROUND(cdd::numeric, 2) AS cdd, ROUND(extras::numeric, 2) AS extras,
       ROUND(mp::numeric, 2) AS mercado_publico, ROUND(ss::numeric, 2) AS saude_suplementar,
       ROUND(pbm::numeric, 2) AS voucher_descontado,
       ROUND(todas::numeric) AS total_todas_as_fontes,
       ROUND(so_cdd::numeric) AS total_so_cdd,
       ROUND((100 * (MAX(todas) FILTER (WHERE periodo = 'atual') OVER () - MAX(todas) FILTER (WHERE periodo = 'anterior') OVER ())
             / NULLIF(MAX(todas) FILTER (WHERE periodo = 'anterior') OVER (), 0))::numeric, 1) AS var_todas_as_fontes_pct,
       ROUND((100 * (MAX(so_cdd) FILTER (WHERE periodo = 'atual') OVER () - MAX(so_cdd) FILTER (WHERE periodo = 'anterior') OVER ())
             / NULLIF(MAX(so_cdd) FILTER (WHERE periodo = 'anterior') OVER (), 0))::numeric, 1) AS var_so_cdd_pct
FROM por_periodo
ORDER BY periodo DESC;
```

Conferido no RDS em 23/09/2026: com todas as fontes, **4.306** (1–20/09) contra **5.004** (1–20/08),
**−14,0%**; só CDD, −8,7%. A diferença é Extras (189), MP (33) e SS (66) de agosto, que em setembro
ainda estão zerados por falta de carga. A resposta mostra os dois totais e diz que o −14,0% exagera a
queda até essas fontes chegarem.

#### Meta × resultado

> ⚠️ **O schema `remuneracao_fv` ainda não existe no banco AWS.** Se a consulta falhar, responda que
> a informação de meta não está disponível no momento — não estime a meta.

A meta mensal de cada representante está em `remuneracao_fv.fato_remuneracao`: **`fat_alvo_bonus`**
é a meta e **`fat_base`** é o faturamento base. O realizado é o faturamento da `vw_sell_out`
(unidades × ticket médio) do mesmo `cod_ct` no mesmo mês.

*"Os representantes bateram a meta em agosto?"*

```sql
-- B05 · Meta × resultado por representante no mês
WITH realizado AS (
  SELECT s.cod_ct,
         date_trunc('month', s.date)::date AS mes,
         SUM((s.cdd + s.extras + s.mp + s.ss - s.pbm) *
             CASE s.cod_apres WHEN 259434 THEN 302.00
                              WHEN 234194 THEN 799.30
                              WHEN 309653 THEN 174.30
                              WHEN 254655 THEN 286.00 END) AS faturamento
  FROM cddd.vw_sell_out s
  GROUP BY 1, 2
)
SELECT r.mes, r.nome_representante, r.setor, r.nivel,
       r.fat_base,
       r.fat_alvo_bonus                                                     AS meta,
       ROUND(re.faturamento::numeric, 2)                                    AS faturamento_realizado,
       ROUND((100 * re.faturamento / NULLIF(r.fat_alvo_bonus, 0))::numeric, 1) AS pct_meta,
       ROUND((100 * re.faturamento / NULLIF(r.fat_base, 0))::numeric, 1)       AS pct_fat_base
FROM remuneracao_fv.fato_remuneracao r
LEFT JOIN realizado re ON re.cod_ct = r.cod_ct AND re.mes = r.mes
WHERE r.mes = :mes                    -- 1º dia do mês, ex.: '2026-08-01'
ORDER BY pct_meta DESC NULLS LAST;
```

*"Como está a equipe do Gabriel contra a meta?"*

```sql
-- B06 · Meta × resultado por GR no mês
WITH realizado AS (
  SELECT s.cod_ct,
         date_trunc('month', s.date)::date AS mes,
         SUM((s.cdd + s.extras + s.mp + s.ss - s.pbm) *
             CASE s.cod_apres WHEN 259434 THEN 302.00
                              WHEN 234194 THEN 799.30
                              WHEN 309653 THEN 174.30
                              WHEN 254655 THEN 286.00 END) AS faturamento
  FROM cddd.vw_sell_out s
  GROUP BY 1, 2
)
SELECT g.nome_gr AS gr,
       SUM(r.fat_base)       AS fat_base,
       SUM(r.fat_alvo_bonus) AS meta,
       ROUND(SUM(re.faturamento)::numeric, 2) AS faturamento_realizado,
       ROUND((100 * SUM(re.faturamento) / NULLIF(SUM(r.fat_alvo_bonus), 0))::numeric, 1) AS pct_meta
FROM remuneracao_fv.fato_remuneracao r
LEFT JOIN realizado re ON re.cod_ct = r.cod_ct AND re.mes = r.mes
LEFT JOIN cddd.dim_gr g ON g.cod_gr = r.cod_gr
WHERE r.mes = :mes
GROUP BY 1
ORDER BY pct_meta DESC NULLS LAST;
```

#### Fontes de vendas extras e Mercado Público

Quando o usuário pedir o detalhe de vendas extras, Mercado Público ou Saúde Suplementar, consulte a
tabela fonte. Ignore linhas com `deleted_at` preenchido (exclusão lógica).

*"Quais foram as vendas extras do mês, por produto?"*

```sql
-- B07 · Vendas extras por mês e produto
SELECT date_trunc('month', e.data_venda)::date AS mes,
       e.produto,
       SUM(e.qtd) AS unidades
FROM cddd.vendas_extras e
WHERE e.deleted_at IS NULL
  AND e.data_venda >= :data_ini AND e.data_venda < :data_fim
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

*"Quais representantes lançaram vendas extras?"*

```sql
-- B08 · Vendas extras por representante (território)
SELECT fv.desc_territorio AS representante,
       SUM(e.qtd) AS unidades
FROM cddd.vendas_extras e
LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
       ON fv.cod_territorio = e.cod_territorio
WHERE e.deleted_at IS NULL
  AND e.data_venda >= :data_ini AND e.data_venda < :data_fim
GROUP BY 1
ORDER BY unidades DESC;
```

*"Quanto vendemos para Mercado Público?" / "E para Saúde Suplementar?"*

```sql
-- B09 · Mercado Público e Saúde Suplementar por mês, modalidade e produto
SELECT date_trunc('month', v.data_venda)::date AS mes,
       v.modalidade,                  -- 'Mercado Público' ou 'Saúde Suplementar'
       v.produto,
       SUM(v.frascos)        AS unidades,
       SUM(v.total_sell_out) AS valor
FROM cddd.venda_mercado_publico v
WHERE v.deleted_at IS NULL
  AND v.data_venda >= :data_ini AND v.data_venda < :data_fim
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 4 DESC;
```

### 2.2 Sell Out Ease PDVs (CDD)

Dispensação de unidades Ease nos PDVs. **PDV só tem unidade CDD** — extras, Mercado Público e
Saúde Suplementar não existem por PDV.

A query abaixo é a referência: ela já aplica os filtros padrão do Sell Out Ease (tipo de
transação, informantes que duplicam venda e canal hospitalar). **Mantenha esses filtros em toda
consulta derivada.**

*"Quantas unidades CDD a Ease dispensou mês a mês?"*

```sql
-- B10 · Unidades CDD Ease mês a mês (query de referência)
SELECT
    TO_CHAR(fc.cod_anomes, 'YYYYMM') AS anomes,
    SUM(fc.und / 1000.0) AS total_und
FROM cddd.fato_cdd fc
LEFT JOIN cddd.pdvs pdvs ON pdvs.cod_pdv = fc.cod_pdv::bigint
LEFT JOIN cddd.dim_utc_setor_hist fv
       ON fv.utc = pdvs.cod_utc::text
      AND fc.cod_anomes >= fv.dt_inicio
      AND is_current
LEFT JOIN cddd.apres a ON a.cod_apresentacao = fc.cod_apresentacao::bigint
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = pdvs.cod_subcanal
LEFT JOIN cddd.informantes di ON di.cod_informante = fc.cod_informante::integer
WHERE ((fc.cod_anomes >= '2025-07-01' AND fc.cod_tipo_transacao = '1')
       OR fc.cod_anomes < '2025-07-01')
  AND ((fc.cod_anomes <= '2024-10-01' AND di.desc_informante NOT IN ('DIMED DISTR', 'PORTAL'))
       OR (fc.cod_anomes > '2024-10-01' AND di.desc_informante NOT SIMILAR TO '%(DIMED|LS|PORTAL|FARMACIAS ASSOCIADAS)%'))
  AND dc_1.desc_canal <> 'HOSPITALAR'
GROUP BY TO_CHAR(fc.cod_anomes, 'YYYYMM')
ORDER BY anomes DESC;
```

*"Quantas unidades a Raia dispensou por mês?"*

```sql
-- B11 · Unidades CDD de uma rede (rede = desc_grupo_informante)
SELECT
    TO_CHAR(fc.cod_anomes, 'YYYYMM') AS anomes,
    di.desc_grupo_informante AS rede,
    SUM(fc.und / 1000.0) AS total_und
FROM cddd.fato_cdd fc
LEFT JOIN cddd.pdvs pdvs ON pdvs.cod_pdv = fc.cod_pdv::bigint
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = pdvs.cod_subcanal
LEFT JOIN cddd.informantes di ON di.cod_informante = fc.cod_informante::integer
WHERE ((fc.cod_anomes >= '2025-07-01' AND fc.cod_tipo_transacao = '1')
       OR fc.cod_anomes < '2025-07-01')
  AND ((fc.cod_anomes <= '2024-10-01' AND di.desc_informante NOT IN ('DIMED DISTR', 'PORTAL'))
       OR (fc.cod_anomes > '2024-10-01' AND di.desc_informante NOT SIMILAR TO '%(DIMED|LS|PORTAL|FARMACIAS ASSOCIADAS)%'))
  AND dc_1.desc_canal <> 'HOSPITALAR'
  AND di.desc_grupo_informante ILIKE '%' || :rede || '%'   -- remova para ver todas as redes
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

*"Quanto o PDV de CNPJ X vendeu por mês e produto?"*

```sql
-- B12 · Unidades CDD de um PDV (CNPJ) por mês e SKU
SELECT
    TO_CHAR(fc.cod_anomes, 'YYYYMM') AS anomes,
    a.desc_apresentacao,
    SUM(fc.und / 1000.0) AS total_und
FROM cddd.fato_cdd fc
LEFT JOIN cddd.pdvs pdvs ON pdvs.cod_pdv = fc.cod_pdv::bigint
LEFT JOIN cddd.apres a ON a.cod_apresentacao = fc.cod_apresentacao::bigint
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = pdvs.cod_subcanal
LEFT JOIN cddd.informantes di ON di.cod_informante = fc.cod_informante::integer
WHERE ((fc.cod_anomes >= '2025-07-01' AND fc.cod_tipo_transacao = '1')
       OR fc.cod_anomes < '2025-07-01')
  AND ((fc.cod_anomes <= '2024-10-01' AND di.desc_informante NOT IN ('DIMED DISTR', 'PORTAL'))
       OR (fc.cod_anomes > '2024-10-01' AND di.desc_informante NOT SIMILAR TO '%(DIMED|LS|PORTAL|FARMACIAS ASSOCIADAS)%'))
  AND dc_1.desc_canal <> 'HOSPITALAR'
  AND lpad(regexp_replace(pdvs.cnpj_pdv, '\D', '', 'g'), 14, '0') = :cnpj
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

*"Quais PDVs mais venderam Extrato em São Paulo?"*

```sql
-- B13 · Ranking de PDVs por unidades CDD
SELECT
    pdvs.cnpj_pdv, pdvs.desc_pdv, pdvs.cidade, pdvs.uf,
    SUM(fc.und / 1000.0) AS total_und
FROM cddd.fato_cdd fc
LEFT JOIN cddd.pdvs pdvs ON pdvs.cod_pdv = fc.cod_pdv::bigint
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = pdvs.cod_subcanal
LEFT JOIN cddd.informantes di ON di.cod_informante = fc.cod_informante::integer
WHERE ((fc.cod_anomes >= '2025-07-01' AND fc.cod_tipo_transacao = '1')
       OR fc.cod_anomes < '2025-07-01')
  AND ((fc.cod_anomes <= '2024-10-01' AND di.desc_informante NOT IN ('DIMED DISTR', 'PORTAL'))
       OR (fc.cod_anomes > '2024-10-01' AND di.desc_informante NOT SIMILAR TO '%(DIMED|LS|PORTAL|FARMACIAS ASSOCIADAS)%'))
  AND dc_1.desc_canal <> 'HOSPITALAR'
  AND fc.cod_anomes >= :data_ini AND fc.cod_anomes < :data_fim
  AND fc.cod_apresentacao = '259434'   -- Extrato; remova para todos os SKUs
  AND pdvs.uf = :uf                    -- ou pdvs.cidade, ou pdvs.cod_utc
GROUP BY 1, 2, 3, 4
ORDER BY total_und DESC
LIMIT 50;
```

*"Quantas unidades de cada produto foram dispensadas nos PDVs?"*

```sql
-- B14 · Unidades CDD por SKU, mês a mês
SELECT
    TO_CHAR(fc.cod_anomes, 'YYYYMM') AS anomes,
    a.desc_apresentacao,
    SUM(fc.und / 1000.0) AS total_und
FROM cddd.fato_cdd fc
LEFT JOIN cddd.pdvs pdvs ON pdvs.cod_pdv = fc.cod_pdv::bigint
LEFT JOIN cddd.apres a ON a.cod_apresentacao = fc.cod_apresentacao::bigint
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = pdvs.cod_subcanal
LEFT JOIN cddd.informantes di ON di.cod_informante = fc.cod_informante::integer
WHERE ((fc.cod_anomes >= '2025-07-01' AND fc.cod_tipo_transacao = '1')
       OR fc.cod_anomes < '2025-07-01')
  AND ((fc.cod_anomes <= '2024-10-01' AND di.desc_informante NOT IN ('DIMED DISTR', 'PORTAL'))
       OR (fc.cod_anomes > '2024-10-01' AND di.desc_informante NOT SIMILAR TO '%(DIMED|LS|PORTAL|FARMACIAS ASSOCIADAS)%'))
  AND dc_1.desc_canal <> 'HOSPITALAR'
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

*"Quanto o brick X vendeu nos últimos 90 dias?"* — conte a partir da data máxima da base, não de hoje.

```sql
-- B15 · Unidades CDD de um brick nos últimos 90 dias, por PDV
SELECT
    pdvs.desc_pdv,
    SUM(fc.und / 1000.0) AS total_und
FROM cddd.fato_cdd fc
LEFT JOIN cddd.pdvs pdvs ON pdvs.cod_pdv = fc.cod_pdv::bigint
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = pdvs.cod_subcanal
LEFT JOIN cddd.informantes di ON di.cod_informante = fc.cod_informante::integer
WHERE fc.cod_tipo_transacao = '1'
  AND di.desc_informante NOT SIMILAR TO '%(DIMED|LS|PORTAL|FARMACIAS ASSOCIADAS)%'
  AND dc_1.desc_canal <> 'HOSPITALAR'
  AND pdvs.cod_utc = :cod_utc
  AND fc.cod_anomes >= (SELECT MAX(cod_anomes) FROM cddd.fato_cdd) - INTERVAL '90 days'
GROUP BY 1
ORDER BY total_und DESC;
```

*"Quais as 10 cidades com mais unidades Ease dispensadas no território do Hermes no último trimestre?"*

```sql
-- B16 · Top 10 cidades em unidades CDD Ease no território de um representante, último trimestre
SELECT
    pdvs.cidade,
    pdvs.uf,
    SUM(fc.und / 1000.0) AS total_und
FROM cddd.fato_cdd fc
LEFT JOIN cddd.pdvs pdvs ON pdvs.cod_pdv = fc.cod_pdv::bigint
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = pdvs.cod_subcanal
LEFT JOIN cddd.informantes di ON di.cod_informante = fc.cod_informante::integer
WHERE ((fc.cod_anomes >= '2025-07-01' AND fc.cod_tipo_transacao = '1')
       OR fc.cod_anomes < '2025-07-01')
  AND ((fc.cod_anomes <= '2024-10-01' AND di.desc_informante NOT IN ('DIMED DISTR', 'PORTAL'))
       OR (fc.cod_anomes > '2024-10-01' AND di.desc_informante NOT SIMILAR TO '%(DIMED|LS|PORTAL|FARMACIAS ASSOCIADAS)%'))
  AND dc_1.desc_canal <> 'HOSPITALAR'
  AND pdvs.cod_utc IN (SELECT cod_utc FROM cddd.forca_vendas
                       WHERE desc_territorio ILIKE '%HERMES%')      -- troque o representante aqui
  -- último trimestre = os 3 últimos meses fechados da base
  AND fc.cod_anomes >= (SELECT date_trunc('month', MAX(cod_anomes)) - INTERVAL '3 months' FROM cddd.fato_cdd)
  AND fc.cod_anomes <  (SELECT date_trunc('month', MAX(cod_anomes)) FROM cddd.fato_cdd)
GROUP BY 1, 2
ORDER BY total_und DESC
LIMIT 10;
```

Por cidade só existe unidade **CDD**: extras, Mercado Público e Saúde Suplementar não têm PDV.

### 2.3 Sell Out Mercado (TD)

Mercado de cannabis inteiro (todos os laboratórios). Fonte: `td.fato_td`.

**Sempre que pedirem faturamento ou unidades de mercado, pergunte se é Varejo, Mercado Público
ou Total:**

| Resposta | Filtro |
|---|---|
| Varejo | `dc_1.desc_canal <> 'HOSPITALAR'` |
| Mercado Público | `dc_1.desc_canal = 'HOSPITALAR'` |
| Total | sem filtro de canal |

- `cod_anomes` é texto `'YYYYMM'` (ex.: `'202608'`).
- `und` e `valor_` vêm ×1000: divida por 1000.
- Laboratório: `td.fato_td.cod_apresentacao` → `cddd.apres.cod_marca` → `cddd.prod.cod_fab` →
  `cddd.fab.desc_fab` (nome) / `desc_sigla_fab` (`'EAS'` = Ease).
- Representante: `td.fato_td.cod_utc` → `cddd.forca_vendas.cod_utc`.

#### ⚠️ Classificação de produto — Isolado, Extrato e Mevatyl

**As palavras "isolado" e "extrato" NÃO existem em `desc_apresentacao`.** Procurar
`desc_apresentacao ILIKE '%ISOLADO%'` devolve zero linhas — os produtos se chamam
`CANABIDIOL ...` (que são os isolados) e `EXT CANNABIS ...` (que são os extratos).

A classificação oficial, a mesma do Power BI, é derivada do nome, nesta ordem:

| Ordem | Condição sobre `upper(desc_apresentacao)` | Classe |
|---|---|---|
| 1 | contém `MEVATYL` | Mevatyl |
| 2 | contém `EXT` | Extrato |
| 3 | qualquer outro caso | **Isolado** |

```text
CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
     WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
     ELSE 'Isolado' END AS classe
```

A ordem importa: o Mevatyl é testado antes do `EXT`. Como o Isolado é o `ELSE`, qualquer
apresentação nova cai nele por padrão.

**Apresentação nova pode ainda não estar em `cddd.apres`**: use `td.apres` como reserva, com
`COALESCE(a.desc_apresentacao, ta.desc_apresentacao)` e
`COALESCE(a.cod_marca, ta.cod_marca)`. Hoje são 5 produtos nessa situação (4 da Life Science e
1 da TTH), e sem o `COALESCE` eles somem do resultado.

**Faixas por concentração** (só quando pedirem esse detalhe). A concentração vem de
`cddd.apres.und_concentracao` e, quando nula, do número em `cddd.apres.desc_concentracao`.
Exceção conhecida: `EXT DE CANNABIS ACH ACH 3676MG/ML...` vale **36,76**.

| Classe | Concentração | Faixa |
|---|---|---|
| Extrato | `< 80` ou `= 200` | Extrato < 0.2% THC |
| Extrato | `100` a `133,33` ou `>= 160` | Extrato > 0,20% THC |
| Isolado | `<= 35` | até 35 mg/mL |
| Isolado | `<= 50` | até 50 mg/mL |
| Isolado | `<= 150` | 50 a 149 mg/mL |
| Isolado | `> 150` | acima de 150 mg/mL |

*"Qual o faturamento do mercado varejo por mês?"*

```sql
-- B20 · Faturamento mercado VAREJO por mês
SELECT
  f.cod_anomes,
  SUM(f.valor_) / 1000 AS faturamento_varejo
FROM td.fato_td f
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = f.cod_subcanal
WHERE dc_1.desc_canal <> 'HOSPITALAR'
GROUP BY 1
ORDER BY 1 DESC;
```

*"Qual o faturamento do Mercado Público?"*

```sql
-- B21 · Faturamento MERCADO PÚBLICO por mês (para o Total, remova o filtro de canal)
SELECT
  f.cod_anomes,
  SUM(f.valor_) / 1000 AS faturamento_mercado_publico
FROM td.fato_td f
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = f.cod_subcanal
WHERE dc_1.desc_canal = 'HOSPITALAR'
GROUP BY 1
ORDER BY 1 DESC;
```

*"Quantas unidades o mercado varejo vendeu por mês?"*

```sql
-- B22 · Unidades mercado VAREJO por mês
SELECT
  f.cod_anomes,
  SUM(f.und) / 1000 AS unidades_varejo
FROM td.fato_td f
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = f.cod_subcanal
WHERE dc_1.desc_canal <> 'HOSPITALAR'
GROUP BY 1
ORDER BY 1 DESC;
```

*"Quais SKUs mais faturam no varejo?"*

```sql
-- B23 · Faturamento mercado VAREJO por SKU
SELECT
  a.cod_apresentacao,
  a.desc_apresentacao,
  SUM(f.valor_) / 1000 AS faturamento_varejo,
  SUM(f.und) / 1000    AS unidades_varejo
FROM td.fato_td f
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = f.cod_subcanal
LEFT JOIN cddd.apres a ON a.cod_apresentacao = f.cod_apresentacao
WHERE dc_1.desc_canal <> 'HOSPITALAR'
  AND f.cod_anomes BETWEEN :anomes_ini AND :anomes_fim
GROUP BY 1, 2
ORDER BY faturamento_varejo DESC
LIMIT 50;
```

#### ⭐ Market share de faturamento varejo por laboratório

**É a pergunta mais comum desta seção.**

*"Qual o market share de faturamento por laboratório no varejo?"*

```sql
-- B24 · Market share de faturamento VAREJO por laboratório
WITH base AS (
  SELECT
    COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO') AS laboratorio,
    SUM(f.valor_) / 1000 AS faturamento
  FROM td.fato_td f
  LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = f.cod_subcanal
  LEFT JOIN cddd.apres a    ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN cddd.prod pr    ON pr.cod_marca = a.cod_marca
  LEFT JOIN cddd.fab fb     ON fb.cod_fab = pr.cod_fab
  WHERE dc_1.desc_canal <> 'HOSPITALAR'
    AND f.cod_anomes BETWEEN :anomes_ini AND :anomes_fim
  GROUP BY 1
)
SELECT laboratorio,
       ROUND(faturamento, 2) AS faturamento,
       ROUND(100 * faturamento / SUM(faturamento) OVER (), 2) AS share_pct
FROM base
ORDER BY faturamento DESC;
```

*"Quais os top 10 laboratórios em faturamento no varejo no último trimestre?"*

```sql
-- B25 · Top 10 laboratórios em faturamento VAREJO nos últimos 3 meses da base
WITH base AS (
  SELECT
    COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO') AS laboratorio,
    SUM(f.valor_) / 1000 AS faturamento
  FROM td.fato_td f
  LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = f.cod_subcanal
  LEFT JOIN cddd.apres a    ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN cddd.prod pr    ON pr.cod_marca = a.cod_marca
  LEFT JOIN cddd.fab fb     ON fb.cod_fab = pr.cod_fab
  WHERE dc_1.desc_canal <> 'HOSPITALAR'
    AND f.cod_anomes > (SELECT TO_CHAR(TO_DATE(MAX(cod_anomes), 'YYYYMM') - INTERVAL '3 months', 'YYYYMM')
                        FROM td.fato_td)
  GROUP BY 1
)
SELECT laboratorio,
       ROUND(faturamento, 2) AS faturamento,
       ROUND(100 * faturamento / SUM(faturamento) OVER (), 2) AS share_pct
FROM base
ORDER BY faturamento DESC
LIMIT 10;
```

*"Como evoluiu o market share da Ease no varejo mês a mês?"*

```sql
-- B26 · Market share Ease no faturamento VAREJO, mês a mês
SELECT
  f.cod_anomes,
  SUM(f.valor_) FILTER (WHERE fb.desc_sigla_fab = 'EAS') / 1000 AS faturamento_ease,
  SUM(f.valor_) / 1000                                          AS faturamento_mercado,
  ROUND(100 * SUM(f.valor_) FILTER (WHERE fb.desc_sigla_fab = 'EAS') / NULLIF(SUM(f.valor_), 0), 2) AS share_ease_pct
FROM td.fato_td f
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = f.cod_subcanal
LEFT JOIN cddd.apres a    ON a.cod_apresentacao = f.cod_apresentacao
LEFT JOIN cddd.prod pr    ON pr.cod_marca = a.cod_marca
LEFT JOIN cddd.fab fb     ON fb.cod_fab = pr.cod_fab
WHERE dc_1.desc_canal <> 'HOSPITALAR'
GROUP BY 1
ORDER BY 1 DESC;
```

*"Qual o market share da Ease no território de cada representante?"*

```sql
-- B27 · Market share Ease no faturamento VAREJO por representante
SELECT
  fv.desc_territorio AS representante,
  SUM(f.valor_) FILTER (WHERE fb.desc_sigla_fab = 'EAS') / 1000 AS faturamento_ease,
  SUM(f.valor_) / 1000                                          AS faturamento_mercado,
  ROUND(100 * SUM(f.valor_) FILTER (WHERE fb.desc_sigla_fab = 'EAS') / NULLIF(SUM(f.valor_), 0), 2) AS share_ease_pct
FROM td.fato_td f
LEFT JOIN cddd.canal dc_1        ON dc_1.cod_subcanal = f.cod_subcanal
LEFT JOIN cddd.apres a           ON a.cod_apresentacao = f.cod_apresentacao
LEFT JOIN cddd.prod pr           ON pr.cod_marca = a.cod_marca
LEFT JOIN cddd.fab fb            ON fb.cod_fab = pr.cod_fab
LEFT JOIN cddd.forca_vendas fv   ON fv.cod_utc = f.cod_utc
WHERE dc_1.desc_canal <> 'HOSPITALAR'
  AND f.cod_anomes BETWEEN :anomes_ini AND :anomes_fim
GROUP BY 1
ORDER BY share_ease_pct DESC NULLS LAST;
```

*"Qual o market share da Ease por GR?"*

```sql
-- B28 · Market share Ease no faturamento VAREJO por GR
SELECT
  COALESCE(d.desc_distrito, 'SEM GR') AS gr,
  SUM(f.valor_) FILTER (WHERE fb.desc_sigla_fab = 'EAS') / 1000 AS faturamento_ease,
  SUM(f.valor_) / 1000                                          AS faturamento_mercado,
  ROUND(100 * SUM(f.valor_) FILTER (WHERE fb.desc_sigla_fab = 'EAS') / NULLIF(SUM(f.valor_), 0), 2) AS share_ease_pct
FROM td.fato_td f
LEFT JOIN cddd.canal dc_1        ON dc_1.cod_subcanal = f.cod_subcanal
LEFT JOIN cddd.apres a           ON a.cod_apresentacao = f.cod_apresentacao
LEFT JOIN cddd.prod pr           ON pr.cod_marca = a.cod_marca
LEFT JOIN cddd.fab fb            ON fb.cod_fab = pr.cod_fab
LEFT JOIN cddd.forca_vendas fv   ON fv.cod_utc = f.cod_utc
LEFT JOIN cddd.fv_territorio t   ON t.cod_territorio = fv.cod_territorio
LEFT JOIN cddd.fv_distrito d     ON d.cod_distrito = t.cod_distrito
WHERE dc_1.desc_canal <> 'HOSPITALAR'
  AND f.cod_anomes BETWEEN :anomes_ini AND :anomes_fim
GROUP BY 1
ORDER BY share_ease_pct DESC NULLS LAST;
```

*"Em quais estados a Ease tem maior market share?"*

```sql
-- B29 · Market share Ease no faturamento VAREJO por UF
SELECT
  u.uf,
  SUM(f.valor_) FILTER (WHERE fb.desc_sigla_fab = 'EAS') / 1000 AS faturamento_ease,
  SUM(f.valor_) / 1000                                          AS faturamento_mercado,
  ROUND(100 * SUM(f.valor_) FILTER (WHERE fb.desc_sigla_fab = 'EAS') / NULLIF(SUM(f.valor_), 0), 2) AS share_ease_pct
FROM td.fato_td f
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = f.cod_subcanal
LEFT JOIN cddd.apres a    ON a.cod_apresentacao = f.cod_apresentacao
LEFT JOIN cddd.prod pr    ON pr.cod_marca = a.cod_marca
LEFT JOIN cddd.fab fb     ON fb.cod_fab = pr.cod_fab
LEFT JOIN cddd.utc u      ON u.cod_utc = f.cod_utc
WHERE dc_1.desc_canal <> 'HOSPITALAR'
  AND f.cod_anomes BETWEEN :anomes_ini AND :anomes_fim
GROUP BY 1
ORDER BY share_ease_pct DESC NULLS LAST;
```

*"Quais as 10 cidades com mais unidades Prati-Donaduzzi no varejo, no território do Hermes, no último trimestre?"*

```sql
-- B30 · Top 10 cidades em unidades VAREJO de um laboratório no território de um representante, último trimestre
SELECT
  u.cidade,
  u.uf,
  SUM(f.und) / 1000 AS unidades_varejo
FROM td.fato_td f
LEFT JOIN cddd.canal dc_1 ON dc_1.cod_subcanal = f.cod_subcanal
LEFT JOIN cddd.apres a    ON a.cod_apresentacao = f.cod_apresentacao
LEFT JOIN cddd.prod pr    ON pr.cod_marca = a.cod_marca
LEFT JOIN cddd.fab fb     ON fb.cod_fab = pr.cod_fab
LEFT JOIN cddd.utc u      ON u.cod_utc = f.cod_utc
WHERE dc_1.desc_canal <> 'HOSPITALAR'                 -- varejo
  AND fb.desc_sigla_fab = 'P.D'                       -- PRATI-DONADUZZI; troque o laboratório aqui ('EAS' = Ease)
  AND f.cod_utc IN (SELECT cod_utc FROM cddd.forca_vendas
                    WHERE desc_territorio ILIKE '%HERMES%')   -- troque o representante aqui
  -- último trimestre = os 3 últimos meses da base
  AND f.cod_anomes > (SELECT TO_CHAR(TO_DATE(MAX(cod_anomes), 'YYYYMM') - INTERVAL '3 months', 'YYYYMM')
                      FROM td.fato_td)
GROUP BY 1, 2
ORDER BY unidades_varejo DESC
LIMIT 10;
```

#### ⭐ Unidades e market share por apresentação, de uma classe de produto

*"Quantas unidades de Produtos Isolados foram vendidas no MAT, com o market share?"*

Junta tudo que esta seção tem de regra: a classificação pelo nome, o `COALESCE` com
`td.apres`, os dois canais e o share dentro de cada canal. **É a consulta quando pedirem
Varejo e Mercado Público juntos**: cada canal com o seu total e o seu share, nunca somados. Para Extrato ou Mevatyl, troque
só o `WHERE classe`.

```sql
-- B31 · Unidades e share por apresentação, de uma classe (Isolado / Extrato / Mevatyl)
WITH base AS (
  SELECT CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS apresentacao,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO') AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END AS classe,
         f.und / 1000.0 AS unidades
  FROM td.fato_td f
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  WHERE f.cod_anomes BETWEEN :anomes_ini AND :anomes_fim   -- MAT = 12 meses fechados
)
SELECT canal, apresentacao, laboratorio,
       SUM(unidades) AS unidades,
       ROUND(100 * SUM(unidades) / SUM(SUM(unidades)) OVER (PARTITION BY canal), 2) AS share_canal
FROM base
WHERE classe = 'Isolado'
GROUP BY 1, 2, 3
ORDER BY canal, unidades DESC;
```

**MAT pedido além da base.** O TD é mercado auditado e fecha com atraso: o último mês
disponível é `(SELECT MAX(cod_anomes) FROM td.fato_td)`. Quem pede "MAT Outubro/26" em
setembro/26 está pedindo 12 meses dos quais só 10 existem. Não devolva um MAT capenga nem
invente os meses que faltam: use o MAT dos 12 meses fechados (`202509`–`202608`, se o máximo
for `202608`) e **diga na resposta qual período foi usado e por quê**.

Conferido no RDS em 22/09/2026, MAT set/25–ago/26: Isolados somam **729.227** unidades no
Varejo (39 apresentações) e **121.112** no Mercado Público (34). Maior do varejo:
Prati-Donaduzzi 20 mg/mL 30 mL, 215.844 un (29,60%).

#### ⭐ Análises avançadas de mercado: classe, canal e período

Perguntas de análise que exigem raciocínio, não só um filtro. Quase todas são a mesma base — o
mercado classificado por classe e canal — com uma pergunta diferente em cima. **Confirme antes os
parâmetros que o usuário não disse:**

| Parâmetro | Valores |
|---|---|
| **Classe** | `Isolado` · `Extrato` · `Mevatyl` |
| **Canal** | `Varejo` (tudo que não é `HOSPITALAR`) · `Mercado Público` (`HOSPITALAR`) · os dois |
| **Período** | MAT (12 meses fechados), trimestre, mês, YTD |
| **Laboratório** | `EASE LABS` ou qualquer concorrente da `cddd.fab` |

**Padrão quando a pergunta não disser:** canal **Varejo** e período **último MAT fechado**. Use o
padrão, diga na resposta qual foi e ofereça o outro canal — não devolva uma pergunta.

Regras que valem para todas:

- **Share = parte ÷ total da mesma classe no mesmo canal.** Nunca misture canais no denominador.
- `und` e `valor_` vêm ×1000: divida por 1000 (inclusive nos cortes de `HAVING`).
- A classe vem do nome (ver ⚠️ acima), com o `COALESCE` de `td.apres` para produto novo.
- Ease = `laboratorio = 'EASE LABS'` no bloco abaixo. SKUs Ease: `234194` Isolado 100 mg/mL 30 mL ·
  `254655` Isolado 100 mg/mL 10 mL · `309653` Isolado 20 mg/mL 30 mL · `259434` Extrato 36,76 mg/mL
  30 mL.
- Os números abaixo foram conferidos no RDS em **23/09/2026**, MAT = set/25 a ago/26 (`'202509'` a
  `'202608'`). Mudam a cada carga; servem para conferir o caminho e a ordem de grandeza.

*"Quanto cada classe vende em cada canal?"* — o bloco `mercado` desta consulta é a base de todas as
seguintes; reaproveite-o para qualquer pergunta nova de mercado por classe.

```sql
-- B32 · Base de mercado por classe e canal (bloco reutilizável)
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
)
SELECT classe, canal,
       SUM(und)/1000 AS unidades,
       ROUND(100*SUM(und)/SUM(SUM(und)) OVER (PARTITION BY canal), 2) AS share_no_canal
FROM mercado
WHERE cod_anomes BETWEEN '202509' AND '202608'          -- MAT
GROUP BY 1, 2
ORDER BY canal, unidades DESC;
```

Varejo: Isolado 729.227 un. (74,47%), Extrato 250.001 (25,53%), Mevatyl 31. Mercado Público:
Isolado 121.112 (96,59%), Extrato 3.709, Mevatyl 565.

*"Exporta as unidades vendidas de todos os produtos Isolados no Varejo, com o market share."*
Variações: Extrato · Mercado Público · trimestre ou ano. Para os dois canais lado a lado, use a
**B31**. Uma apresentação pode ter dois códigos e um nome comercial só.

```sql
-- B33 · Unidades e share de uma classe, por apresentação, num canal
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
)
SELECT desc_apres, laboratorio,
       SUM(und)/1000 AS unidades,
       ROUND(100*SUM(und)/SUM(SUM(und)) OVER (), 2) AS share_pct
FROM mercado
WHERE classe = 'Isolado'            -- ou 'Extrato' / 'Mevatyl'
  AND canal  = 'Varejo'             -- ou 'Mercado Público'; para os dois, use a B31
  AND cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1, 2
ORDER BY unidades DESC;
```

39 apresentações, total 729.227 un. Líder: Prati-Donaduzzi VD 20 mg/mL 30 mL, 215.844 un.
(29,60%); depois Mantecorp 23,75 10 mL (65.313) e Greencare 23,75 10 mL (65.207).

*"Em qual faixa de concentração a Ease é mais forte?"* — faixas do Power BI (tabela ⚠️ acima).
Faixa sem venda da Ease aparece com zero, não some da resposta.

```sql
-- B34 · Market share da Ease por faixa de concentração
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal,
         CASE WHEN COALESCE(a.desc_apresentacao, ta.desc_apresentacao) = 'EXT DE CANNABIS ACH ACH 3676MG/ML GT-OR FR X 30ML N03A'
              THEN 36.76
              ELSE replace(COALESCE(NULLIF(regexp_replace(COALESCE(a.und_concentracao, ''), '[^0-9.,].*$', ''), ''),
                                    regexp_replace(COALESCE(a.desc_concentracao, ta.desc_concentracao, ''), '[^0-9.,].*$', '')), ',', '.')::numeric
         END AS conc
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
)
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
       ROUND(100*COALESCE(SUM(und) FILTER (WHERE laboratorio='EASE LABS'), 0)/NULLIF(SUM(und), 0), 2) AS share_ease
FROM mercado
WHERE canal = 'Varejo' AND cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1, 2
ORDER BY un_mercado DESC;
```

A Ease tem **47,65%** da faixa "Isolado 50 a 149 mg/mL" (43.078 de 90.401) e **18,36%** do
"Extrato < 0,2% THC" (38.601 de 210.255), mas só **0,52%** da maior faixa do mercado, "Isolado até
35 mg/mL" (537.341 un.). É essa leitura que explica o share total.

*"Como evoluiu o share da Ease nos Isolados nos últimos 12 meses?"* — share mês a mês, sempre na
mesma classe e canal. Aponte a tendência, não só os números.

```sql
-- B35 · Share da Ease dentro de uma classe, mês a mês
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
)
SELECT cod_anomes,
       SUM(und)/1000 AS un_classe,
       SUM(und) FILTER (WHERE laboratorio='EASE LABS')/1000 AS un_ease,
       ROUND(100*SUM(und) FILTER (WHERE laboratorio='EASE LABS')/NULLIF(SUM(und), 0), 2) AS share_pct
FROM mercado
WHERE classe='Isolado' AND canal='Varejo' AND cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1
ORDER BY 1;
```

Caiu de **6,85%** (set/25) para **5,80%** (ago/26), com piso de 5,67% em jun/26. As unidades da
Ease ficaram estáveis (3,5 a 4 mil/mês) enquanto o mercado cresceu de 57 para 67 mil: perda de
share por crescimento do mercado, não por queda de volume.

*"Crescemos ou perdemos espaço em relação ao MAT passado?"* — os dois MATs completos (24 meses no
filtro), separando o efeito volume do efeito share.

```sql
-- B36 · MAT contra MAT anterior, dentro de uma classe
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
)
SELECT CASE WHEN cod_anomes BETWEEN '202509' AND '202608' THEN 'MAT atual' ELSE 'MAT anterior' END AS periodo,
       SUM(und)/1000 AS un_classe,
       SUM(und) FILTER (WHERE laboratorio='EASE LABS')/1000 AS un_ease,
       ROUND(100*SUM(und) FILTER (WHERE laboratorio='EASE LABS')/NULLIF(SUM(und), 0), 2) AS share_pct
FROM mercado
WHERE classe='Isolado' AND canal='Varejo' AND cod_anomes BETWEEN '202409' AND '202608'
GROUP BY 1
ORDER BY 1 DESC;
```

Mercado 548.638 → **729.227** un. (+32,9%); Ease 39.944 → **45.867** (+14,8%); share 7,28% →
**6,29%**. A Ease cresceu, mas menos que o mercado.

*"Em que posição estamos no mercado de Isolados?"*

```sql
-- B37 · Ranking de laboratórios numa classe e posição da Ease
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
)
SELECT laboratorio,
       SUM(und)/1000 AS unidades,
       ROUND(100*SUM(und)/SUM(SUM(und)) OVER (), 2) AS share_pct,
       RANK() OVER (ORDER BY SUM(und) DESC) AS posicao
FROM mercado
WHERE classe='Isolado' AND canal='Varejo' AND cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1
ORDER BY posicao;
```

1º Prati-Donaduzzi 51,46%, 2º Greencare 11,09%, 3º Eurofarma 9,43%, 4º Mantecorp 9,38%, **5º Ease
Labs 6,29%**, 6º Aché 5,24%.

*"Em quais estados temos mais share nos Isolados?"* — a UF vem do brick (`cddd.utc`), porque a
`td.fato_td` não tem PDV. Corte UFs de volume irrelevante antes de ranquear, senão um estado com
200 unidades lidera a lista.

```sql
-- B38 · Share da Ease numa classe, por UF
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
)
SELECT u.uf,
       SUM(m.und)/1000 AS un_classe,
       SUM(m.und) FILTER (WHERE m.laboratorio='EASE LABS')/1000 AS un_ease,
       ROUND(100*SUM(m.und) FILTER (WHERE m.laboratorio='EASE LABS')/NULLIF(SUM(m.und), 0), 2) AS share_pct
FROM mercado m
LEFT JOIN cddd.utc u ON u.cod_utc = m.cod_utc
WHERE m.classe='Isolado' AND m.canal='Varejo' AND m.cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1
HAVING SUM(m.und) > 1000000        -- ignora UF com menos de 1.000 unidades no período (und vem ×1000)
ORDER BY share_pct DESC;
```

MG 10,48% (7.901 de 75.389), DF 9,21%, SE 8,21%, RJ 7,67%, RS 7,35% — todos acima da média
nacional de 6,29%.

*"Como fica Varejo contra Mercado Público no mesmo produto?"*

```sql
-- B39 · Varejo contra Mercado Público numa classe
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
)
SELECT canal,
       SUM(und)/1000 AS un_classe,
       SUM(und) FILTER (WHERE laboratorio='EASE LABS')/1000 AS un_ease,
       ROUND(100*SUM(und) FILTER (WHERE laboratorio='EASE LABS')/NULLIF(SUM(und), 0), 2) AS share_pct
FROM mercado
WHERE classe='Isolado' AND cod_anomes BETWEEN '202509' AND '202608'
GROUP BY 1;
```

Varejo 729.227 un. com 6,29% de share; Mercado Público 121.112 un. com **2,40%**. O Mercado
Público é 14% do volume da classe e a Ease é bem menos presente nele.

*"Me dá a lista de todas as apresentações e o ticket médio de cada uma no período."* Variações: uma
classe · um canal · um laboratório · outro período.

- **Concorrentes:** ticket = `valor_ ÷ und` do painel (os dois ×1000, a divisão dispensa o ajuste).
  É preço de mercado no canal, não preço de tabela.
- **Ease: não use o preço do painel.** O ticket é definido pela empresa e entra fixo, por
  `cod_apresentacao`: `234194` Isolado 30 = R$ 799,00 · `254655` Isolado 10 = R$ 286,00 · `259434`
  Extrato = R$ 302,00 · `309653` Isolado 20 = R$ 174,30.
- Apresentação Ease **sem ticket mapeado** sai com o valor do painel e é sinalizada (hoje, a
  `CANNABIS SATIVA EAS EAS 79,14MG`, com 1 unidade no MAT). SKU novo da Ease sem ticket: avise,
  não invente preço.
- A lista traz **todas** as apresentações com venda no recorte, não só as maiores.
- Deixe claro na resposta que o ticket da Ease é preço interno e o dos concorrentes é preço de
  mercado: naturezas diferentes na mesma coluna.

```sql
-- B40 · Ticket médio de cada apresentação (Ease com preço fixo)
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
),
ticket_ease (cod_apresentacao, produto, preco) AS (
  VALUES (234194, 'Isolado 30', 799.00::numeric),
         (254655, 'Isolado 10', 286.00),
         (259434, 'Extrato',    302.00),
         (309653, 'Isolado 20', 174.30)
)
SELECT m.desc_apres AS apresentacao,
       m.laboratorio,
       m.classe,
       m.cod_apresentacao,
       SUM(m.und)/1000 AS unidades,
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
ORDER BY unidades DESC;
```

Varejo: **58 apresentações**. Ease (fixo): Extrato R$ 302,00 (38.601 un.), Isolado 30 R$ 799,00
(26.083), Isolado 10 R$ 286,00 (16.994), Isolado 20 R$ 174,30 (2.789). Concorrentes: Prati VD
20 mg/mL 30 mL R$ 182,93 (215.844 un.), Prati VD 20 mg/mL 10 mL R$ 60,63 (o menor), Mantecorp
23,75 10 mL R$ 137,93, Greencare 23,75 10 mL R$ 140,36. Maior ticket: Mevatyl, R$ 3.150,23.

*"Em quantos bricks o mercado vende Isolado e em quantos nós vendemos?"* — por brick (`cod_utc`),
porque o mercado não tem PDV. "Não vendeu" é ausência de venda no período, não de cadastro.

```sql
-- B41 · Cobertura de bricks: onde o mercado vende e a Ease não
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
)
SELECT COUNT(*) FILTER (WHERE un_mercado > 0) AS bricks_com_mercado,
       COUNT(*) FILTER (WHERE un_ease > 0)    AS bricks_com_ease,
       ROUND(100.0*COUNT(*) FILTER (WHERE un_ease > 0)/NULLIF(COUNT(*) FILTER (WHERE un_mercado > 0), 0), 1) AS cobertura_pct
FROM (
  SELECT cod_utc,
         SUM(und) AS un_mercado,
         SUM(und) FILTER (WHERE laboratorio='EASE LABS') AS un_ease
  FROM mercado
  WHERE classe='Isolado' AND canal='Varejo' AND cod_anomes BETWEEN '202509' AND '202608'
  GROUP BY 1) x;
```

Mercado em **16.918 bricks**, Ease em **5.714**: cobertura de **33,8%**. Para listar os bricks sem
Ease, troque o `SELECT` externo por `WHERE un_mercado > 0 AND COALESCE(un_ease, 0) = 0` e junte com
`cddd.utc` e `cddd.forca_vendas`.

*"Quais produtos mais cresceram no último MAT?"* — corte a base pequena (produto que foi de 3 para
60 unidades cresce 1.900% e não diz nada). Produto que não existia no MAT anterior é lançamento:
trate à parte, sem variação percentual.

```sql
-- B42 · Apresentações que mais cresceram numa classe (MAT contra MAT)
WITH mercado AS (
  SELECT f.cod_apresentacao, f.cod_anomes, f.cod_utc, f.und, f.valor_,
         COALESCE(a.desc_apresentacao, ta.desc_apresentacao) AS desc_apres,
         COALESCE(fb.desc_fab, 'NÃO IDENTIFICADO')            AS laboratorio,
         CASE WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%MEVATYL%' THEN 'Mevatyl'
              WHEN upper(COALESCE(a.desc_apresentacao, ta.desc_apresentacao)) LIKE '%EXT%'     THEN 'Extrato'
              ELSE 'Isolado' END                               AS classe,
         CASE WHEN dc.desc_canal = 'HOSPITALAR' THEN 'Mercado Público' ELSE 'Varejo' END AS canal
  FROM td.fato_td f
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN td.apres ta   ON ta.cod_apresentacao = f.cod_apresentacao   -- produto novo ainda fora da cddd.apres
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = COALESCE(a.cod_marca, ta.cod_marca)
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  LEFT JOIN cddd.canal dc ON dc.cod_subcanal = f.cod_subcanal
)
SELECT desc_apres,
       SUM(und) FILTER (WHERE cod_anomes BETWEEN '202509' AND '202608')/1000 AS mat_atual,
       SUM(und) FILTER (WHERE cod_anomes BETWEEN '202409' AND '202508')/1000 AS mat_anterior,
       ROUND(100.0*(SUM(und) FILTER (WHERE cod_anomes BETWEEN '202509' AND '202608')
                  - SUM(und) FILTER (WHERE cod_anomes BETWEEN '202409' AND '202508'))
             /NULLIF(SUM(und) FILTER (WHERE cod_anomes BETWEEN '202409' AND '202508'), 0), 1) AS var_pct
FROM mercado
WHERE classe='Isolado' AND canal='Varejo' AND cod_anomes BETWEEN '202409' AND '202608'
GROUP BY 1
HAVING SUM(und) FILTER (WHERE cod_anomes BETWEEN '202409' AND '202508') > 5000000   -- base mínima: 5.000 un. no MAT anterior
ORDER BY var_pct DESC;
```

Eurofarma 20 mg/mL 30 mL +443,9% (8.892 → 48.360), Prati VD 20 mg/mL 10 mL +99,5%, Aché 100 mg/mL
30 mL +85,1%, União Química 34,36 +75,5%, Aché 100 mg/mL 10 mL +67,3%.

**Nomes comerciais na resposta.** A descrição do banco (`CANABIDIOL P.D P.D SOL VD 20MG/ML SL-OR FR
X 30ML + 2 SER N03A`) não é o nome que a diretoria usa (`Prati Donaduzzi VD CBD 20 mg/mL - 30mL`).
Quando a entrega for para apresentação, aplique o de-para do Power BI: pares de descrições que
viram o mesmo nome comercial **somam numa linha só** (ex.: `CANNABIS SATIVA EAS EAS 79,14MG` entra
em `Ease Labs CBD 100 mg/mL - 30 mL`); produto novo ainda sem nome comercial (hoje 4 da Life
Science, 1 Biolab 10 mL e 2 da Makrofarma) mantém a descrição original, sinalizado.

---

## 3. Estoque nas Redes e Categoria de PDVs

> **Projeções e forecast:** você **pode projetar** — sell-out, prescrição (PX), PBM e qualquer
> série quantitativa. Escolha o método que o dado comportar (tendência dos últimos meses, média
> móvel, mesmo período do ano anterior, ritmo do mês corrente) e calcule **na própria consulta**,
> deixando claro na resposta o método e o período que serviu de base — projeção é estimativa, não
> medição.
>
> **Só nas projeções de Sell Out ou Sell In da Ease**, acrescente que, para uma visão mais
> assertiva e factual, o usuário deve conferir o **dashboard de Forecast de Reposição**. Em
> projeção de PX, PBM ou outros indicadores, não cite o dashboard: apenas projete.

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `estoque_redes.estoque_redes_cd` | **Histórico** de todas as cargas de estoque das redes, PDVs e CDs | `data_recebimento`, `rede`, `cod_loja`, `cnpj`, `desc_loja`, `tipo` (`'PDV'`/`'CD'`), `cod_ean`, `estoque_qtde` |
| `estoque_redes.vw_estoque_cd_recente` | Mesma estrutura, só a **carga mais recente** de cada rede | idem |
| `estoque_redes.vw_forecast_projecao_cd` | Projeção diária de estoque por CD × SKU | `rede`, `cd`, `produto`, `ean`, `data`, `dia` (0 = hoje), `giro_base`, `dde_base`, `target_dde` |
| `estoque_redes.dim_cd_pdvs` | CD → PDVs que ele abastece | `cd`, `rede`, `cod_loja`, `desc_pdv`, `cnpj_pdv` |
| `tdd.fato_tdd` | Categoria e volume do PDV por grupo e período | `"COD_PDV"`, `"COD_GRUPO"`, `"COD_PERIODO"`, `"CAT_R$_MERCADO"`, `"CAT_UN_MERCADO"` |
| `tdd.dim_pdv` | Cadastro do PDV no TDD (1 CNPJ = 1 `COD_PDV`) | `"COD_PDV"`, `"CNPJ_PDV"` (bigint), `"DESC_PDV"`, `"CIDADE_PDV"`, `"UF_PDV"` |
| `tdd.dim_mercado` | Grupo da categoria | `"COD_GRUPO"`, `"DESC_GRUPO"` (`1` CONCORRENTE · `2` EASELABS · `3` MERCADO) |
| `tdd.dim_periodo` | Períodos trimestrais do TDD | `"COD_PERIODO"`, `"DESC_PERIODO"`, `"TIPO_PERIODO"` |

- **Filtre sempre a coluna `tipo`** conforme a pergunta: `'PDV'` (loja) ou `'CD'` (centro de
  distribuição). O CD vem com `cnpj = '00000000000000'` e é identificado por `desc_loja`
  (o mesmo nome da coluna `cd` do forecast).
- A carga mais recente é **por rede**: cada rede tem sua própria `data_recebimento`. Mostre sempre
  a data junto do número.
- Só 10 redes enviam estoque: ARAUJO, CLAMED, DPSP, DROGAL, INDIANA, PAGUEMENOS, PANVEL, RAIA,
  SAOJOAO e VENANCIO. PDV fora delas não tem estoque zero, tem estoque **não informado**.
- EANs: `7896806601250` Extrato · `7896806601243` Isolado 30 mL · `7896806601281` Isolado 10 mL · `7896806601328` Isolado 20 mg.

### 3.1 Estoque na carga mais recente

*"Quais redes informam estoque e quando foi o último envio de cada uma?"*

```sql
-- C01 · Estoque total e data do último envio de cada rede (query de referência)
SELECT
    data_recebimento,
    rede,
    SUM(estoque_qtde) AS soma_estoque_qtde
FROM estoque_redes.vw_estoque_cd_recente
GROUP BY data_recebimento, rede
ORDER BY rede ASC, data_recebimento DESC;
```

*"Quanto de Extrato as redes têm nas lojas?"*

```sql
-- C02 · Estoque de um SKU, só PDVs, por rede
SELECT
    data_recebimento,
    rede,
    SUM(estoque_qtde) AS soma_estoque_qtde
FROM estoque_redes.vw_estoque_cd_recente
WHERE cod_ean = '7896806601250'   -- apenas um SKU (Extrato)
  AND tipo = 'PDV'                -- apenas PDVs
GROUP BY data_recebimento, rede
ORDER BY rede ASC, data_recebimento DESC;
```

*"Quanto cada rede tem de estoque por produto, nas lojas e nos CDs?"*

```sql
-- C03 · Estoque por rede, tipo e SKU na carga mais recente
SELECT
    rede,
    data_recebimento,
    tipo,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601250') AS extrato,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601243') AS isolado_30ml,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601281') AS isolado_10ml,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601328') AS isolado_20mg,
    SUM(estoque_qtde) AS total
FROM estoque_redes.vw_estoque_cd_recente
GROUP BY 1, 2, 3
ORDER BY 1, 3;
```

*"Quanto de estoque tem a loja de CNPJ X?"*

```sql
-- C04 · Estoque de um PDV (CNPJ) por SKU na carga mais recente
SELECT
    rede,
    desc_loja,
    cod_ean,
    estoque_qtde,
    data_recebimento
FROM estoque_redes.vw_estoque_cd_recente
WHERE tipo = 'PDV'
  AND cnpj = lpad(regexp_replace(:cnpj, '\D', '', 'g'), 14, '0')
  -- AND cod_ean = '7896806601250'  -- um SKU específico
ORDER BY cod_ean;
```

Sem linha: a loja não está na base de estoque (rede fora das 10 ou loja não reportada).

*"Quais CDs da Raia tinham estoque no último recebimento, e quantas unidades?"*

```sql
-- C05 · CDs de uma rede com estoque na carga mais recente (geral e por SKU)
SELECT
    rede,
    desc_loja AS cd,
    data_recebimento,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601250') AS extrato,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601243') AS isolado_30ml,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601281') AS isolado_10ml,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601328') AS isolado_20mg,
    SUM(estoque_qtde) AS total
FROM estoque_redes.vw_estoque_cd_recente
WHERE tipo = 'CD'
  AND rede = :rede                 -- remova para ver os CDs de todas as redes
GROUP BY 1, 2, 3
HAVING SUM(estoque_qtde) > 0       -- remova para listar também os CDs zerados
ORDER BY total DESC;
```

*"Quantas lojas da rede têm Extrato e quantas estão zeradas?"*

```sql
-- C06 · Lojas com e sem estoque de um SKU na carga mais recente, por rede
SELECT
    rede,
    data_recebimento,
    COUNT(DISTINCT cnpj) FILTER (WHERE estoque_qtde > 0)  AS lojas_com_estoque,
    COUNT(DISTINCT cnpj) FILTER (WHERE estoque_qtde <= 0) AS lojas_zeradas,
    SUM(estoque_qtde) AS unidades
FROM estoque_redes.vw_estoque_cd_recente
WHERE tipo = 'PDV'
  AND cod_ean = :ean
GROUP BY 1, 2
ORDER BY 1;
```

*"Quais lojas o CD X abastece e quanto elas têm de estoque?"*

```sql
-- C07 · PDVs abastecidos por um CD, com o estoque de cada um na carga mais recente
SELECT
    m.cd,
    m.desc_pdv,
    m.cnpj_pdv,
    e.cod_ean,
    e.estoque_qtde,
    e.data_recebimento
FROM estoque_redes.dim_cd_pdvs m
LEFT JOIN estoque_redes.vw_estoque_cd_recente e
       ON e.rede = m.rede
      AND e.cnpj = lpad(m.cnpj_pdv, 14, '0')
      AND e.tipo = 'PDV'
      AND e.cod_ean = :ean
WHERE m.cd = :cd
ORDER BY e.estoque_qtde DESC NULLS LAST;
```

### 3.2 Histórico de estoque

Use `estoque_redes.estoque_redes_cd`. As redes enviam mais de uma carga por mês e há meses sem
envio: para comparar meses, use **a última carga de cada mês**. Mês sem carga não aparece no
resultado — informe isso ao usuário, não trate como estoque zero.

*"Como evoluiu o estoque de Extrato nas lojas de cada rede nos últimos 6 meses?"*

```sql
-- C10 · Estoque por rede nos últimos X meses (última carga de cada mês)
WITH cargas AS (
  SELECT rede,
         date_trunc('month', data_recebimento)::date AS mes,
         MAX(data_recebimento) AS ultima_carga_mes
  FROM estoque_redes.estoque_redes_cd
  WHERE tipo = 'PDV'
    AND data_recebimento >= date_trunc('month', CURRENT_DATE) - INTERVAL '6 months'   -- troque X
  GROUP BY 1, 2
)
SELECT c.rede, c.mes, c.ultima_carga_mes,
       SUM(e.estoque_qtde) AS estoque
FROM cargas c
JOIN estoque_redes.estoque_redes_cd e
  ON e.rede = c.rede AND e.data_recebimento = c.ultima_carga_mes
WHERE e.tipo = 'PDV'
  AND e.cod_ean = '7896806601250'  -- remova para todos os SKUs
GROUP BY 1, 2, 3
ORDER BY 1, 2 DESC;
```

*"Como variou o estoque da loja de CNPJ X ao longo das cargas?"*

```sql
-- C11 · Histórico de estoque de um PDV (CNPJ), carga a carga
SELECT
    data_recebimento,
    rede,
    desc_loja,
    cod_ean,
    estoque_qtde
FROM estoque_redes.estoque_redes_cd
WHERE tipo = 'PDV'
  AND cnpj = lpad(regexp_replace(:cnpj, '\D', '', 'g'), 14, '0')
  AND data_recebimento >= CURRENT_DATE - INTERVAL '6 months'
ORDER BY data_recebimento DESC, cod_ean;
```

*"Como variou o estoque do CD X?"*

```sql
-- C12 · Histórico de estoque de um CD, carga a carga, por SKU
SELECT
    data_recebimento,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601250') AS extrato,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601243') AS isolado_30ml,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601281') AS isolado_10ml,
    SUM(estoque_qtde) FILTER (WHERE cod_ean = '7896806601328') AS isolado_20mg
FROM estoque_redes.estoque_redes_cd
WHERE tipo = 'CD'
  AND rede = :rede
  AND desc_loja = :cd
GROUP BY 1
ORDER BY 1 DESC;
```

### 3.3 Ruptura de CD

Fonte: `estoque_redes.vw_forecast_projecao_cd`. **Um CD está em ruptura em um SKU quando o
`dde_base` do dia 0 é menor ou igual a 15.**

- **Sempre filtre `dia = 0`** quando a pergunta for sobre a ruptura de hoje. Os outros dias são a
  projeção de reposição desta própria base e podem ser usados quando a pergunta for de projeção —
  citando o dashboard de Forecast de Reposição como a visão oficial.
- **Sempre avalie por SKU.** Um CD pode estar OK em um SKU e em ruptura em outro. Se o usuário não
  disser o SKU, pergunte ou mostre cada SKU separado — nunca some os SKUs.

*"Quais CDs estão em ruptura de Extrato?"*

```sql
-- C20 · CDs em ruptura de um SKU
SELECT
    rede,
    cd,
    produto,
    ROUND(giro_base, 2) AS giro_base,
    dde_base,
    CASE WHEN dde_base <= 15 THEN 'RUPTURA' ELSE 'OK' END AS status
FROM estoque_redes.vw_forecast_projecao_cd
WHERE dia = 0
  AND ean = :ean                   -- obrigatório: um SKU por vez
  AND dde_base <= 15               -- só quem está em ruptura
ORDER BY dde_base DESC;
```

*"O CD X está em ruptura?"*

```sql
-- C21 · Status de ruptura de um CD, SKU a SKU
SELECT
    rede,
    cd,
    produto,
    ean,
    dde_base,
    CASE WHEN dde_base <= 15 THEN 'RUPTURA' ELSE 'OK' END AS status
FROM estoque_redes.vw_forecast_projecao_cd
WHERE dia = 0
  AND rede = :rede
  AND cd = :cd
ORDER BY ean;
```

*"Quantos CDs de cada rede estão em ruptura, por produto?"*

```sql
-- C22 · Quantidade de CDs em ruptura por rede e SKU
SELECT
    rede,
    produto,
    COUNT(*) FILTER (WHERE dde_base <= 15) AS cds_em_ruptura,
    COUNT(*)                                AS cds_total
FROM estoque_redes.vw_forecast_projecao_cd
WHERE dia = 0
GROUP BY 1, 2
ORDER BY 1, 2;
```

### 3.4 Categoria de PDVs

Existe categoria de **PDV** (esta seção) e categoria de **médico** (seção 1). Se não estiver claro
qual das duas o usuário quer, pergunte.

**Sempre que perguntarem a categoria de um PDV, pergunte antes:**
1. **A categoria é Mercado ou Ease Labs?** (`tdd.dim_mercado."DESC_GRUPO"`)
2. **A categoria é em unidades ou em faturamento?**

Com as duas respostas, consulte `tdd.fato_tdd`:

| Escolha | Filtro / coluna |
|---|---|
| Mercado | `"COD_GRUPO" = 3` |
| Ease Labs | `"COD_GRUPO" = 2` |
| Faturamento | `"CAT_R$_MERCADO"` |
| Unidades | `"CAT_UN_MERCADO"` |

- Use **sempre** `"CAT_R$_MERCADO"` ou `"CAT_UN_MERCADO"`, **também no grupo 2** (Ease Labs).
- Período: o **`COD_PERIODO` mais recente do grupo escolhido** (o primeiro na ordenação ascendente)
  **em que a coluna de categoria está preenchida** (`> 0`). Calcule dentro do grupo, como nas
  queries abaixo, e informe o período usado na resposta.
- O `SEM01_202601` do grupo 3 só tem categoria em **unidades**: `"CAT_R$_MERCADO"` vem 0 em todos os
  PDVs. Por isso a categoria de faturamento no Mercado sai do `TRIM01_202506`, e a de unidades do
  `SEM01_202601`. O grupo 2 (Ease Labs) só tem trimestres: o mais recente é `TRIM01_202506`.
- Categoria **1 = maior**.
- **SEM CAT:** PDV sem categoria no grupo e período escolhidos (o cruzamento volta vazio, ou a
  categoria é 0) é **SEM CAT**. Parta sempre da `tdd.dim_pdv` com `LEFT JOIN` na `tdd.fato_tdd` e use
  `COALESCE(NULLIF(categoria, 0)::text, 'SEM CAT')`. Nunca descarte esses PDVs das contagens.
- O CNPJ do PDV é ligado ao `"COD_PDV"` pela `tdd.dim_pdv`.

*"Qual a categoria de faturamento no mercado do PDV de CNPJ X?"*

```sql
-- C30 · Categoria de um PDV
WITH par AS (
  SELECT 3 AS cod_grupo                  -- 3 = Mercado · 2 = Ease Labs
),
periodo AS (
  SELECT MIN(f."COD_PERIODO") AS cod_periodo
  FROM tdd.fato_tdd f, par
  WHERE f."COD_GRUPO" = par.cod_grupo
    AND f."CAT_R$_MERCADO" > 0           -- unidades: f."CAT_UN_MERCADO" > 0
)
SELECT d."CNPJ_PDV",
       d."DESC_PDV",
       d."CIDADE_PDV",
       d."UF_PDV",
       (SELECT m."DESC_GRUPO" FROM tdd.dim_mercado m WHERE m."COD_GRUPO" = par.cod_grupo) AS grupo,
       p.cod_periodo,
       COALESCE(NULLIF(f."CAT_R$_MERCADO", 0)::text, 'SEM CAT') AS categoria   -- unidades: f."CAT_UN_MERCADO"
FROM tdd.dim_pdv d
CROSS JOIN par
CROSS JOIN periodo p
LEFT JOIN tdd.fato_tdd f
       ON f."COD_PDV" = d."COD_PDV"
      AND f."COD_GRUPO" = par.cod_grupo
      AND f."COD_PERIODO" = p.cod_periodo
WHERE d."CNPJ_PDV" = :cnpj::bigint;
-- Sem linha = CNPJ fora do cadastro do TDD. Com linha e 'SEM CAT' = PDV sem categoria no período.
```

Sem linha: o PDV não tem categoria nesse grupo e período (no grupo 2, normalmente porque não vende Ease).

*"Quantos PDVs existem em cada categoria?"*

```sql
-- C31 · Distribuição de PDVs por categoria, incluindo SEM CAT
WITH par AS (
  SELECT 3 AS cod_grupo                  -- 3 = Mercado · 2 = Ease Labs
),
periodo AS (
  SELECT MIN(f."COD_PERIODO") AS cod_periodo
  FROM tdd.fato_tdd f, par
  WHERE f."COD_GRUPO" = par.cod_grupo
    AND f."CAT_R$_MERCADO" > 0           -- unidades: f."CAT_UN_MERCADO" > 0
)
SELECT COALESCE(NULLIF(f."CAT_R$_MERCADO", 0)::text, 'SEM CAT') AS categoria,  -- unidades: f."CAT_UN_MERCADO"
       COUNT(*) AS pdvs
FROM tdd.dim_pdv d
CROSS JOIN par
CROSS JOIN periodo p
LEFT JOIN tdd.fato_tdd f
       ON f."COD_PDV" = d."COD_PDV"
      AND f."COD_GRUPO" = par.cod_grupo
      AND f."COD_PERIODO" = p.cod_periodo
GROUP BY 1
ORDER BY 1;
```

*"Quais PDVs categoria 1 a 3 existem em Minas Gerais?"*

```sql
-- C32 · PDVs de categoria 1 a 3 de uma UF ou cidade
SELECT
    d."CNPJ_PDV",
    d."DESC_PDV",
    d."CIDADE_PDV",
    d."UF_PDV",
    f."CAT_R$_MERCADO" AS categoria     -- unidades: f."CAT_UN_MERCADO"
FROM tdd.dim_pdv d
JOIN tdd.fato_tdd f ON f."COD_PDV" = d."COD_PDV"
WHERE f."COD_GRUPO" = 3                  -- 3 = Mercado · 2 = Ease Labs
  AND f."COD_PERIODO" = (SELECT MIN("COD_PERIODO") FROM tdd.fato_tdd
                         WHERE "COD_GRUPO" = 3 AND "CAT_R$_MERCADO" > 0)   -- unidades: "CAT_UN_MERCADO" > 0
  AND f."CAT_R$_MERCADO" BETWEEN 1 AND 3
  AND d."UF_PDV" = :uf                   -- ou d."CIDADE_PDV"
ORDER BY categoria, d."CIDADE_PDV"
LIMIT 200;
```

*"Quais PDVs categoria 1 a 3 do mercado estão sem Extrato na última carga?"*

```sql
-- C33 · PDVs de categoria 1 a 3 cruzados com o estoque de um SKU na carga mais recente
SELECT
    e.rede,
    d."DESC_PDV",
    d."CIDADE_PDV",
    d."UF_PDV",
    f."CAT_R$_MERCADO" AS categoria,    -- unidades: f."CAT_UN_MERCADO"
    e.estoque_qtde,
    e.data_recebimento
FROM tdd.fato_tdd f
JOIN tdd.dim_pdv d ON d."COD_PDV" = f."COD_PDV"
JOIN estoque_redes.vw_estoque_cd_recente e
  ON e.cnpj = lpad(d."CNPJ_PDV"::text, 14, '0')
 AND e.tipo = 'PDV'
 AND e.cod_ean = :ean
WHERE f."COD_GRUPO" = 3                  -- 3 = Mercado · 2 = Ease Labs
  AND f."COD_PERIODO" = (SELECT MIN("COD_PERIODO") FROM tdd.fato_tdd
                         WHERE "COD_GRUPO" = 3 AND "CAT_R$_MERCADO" > 0)   -- unidades: "CAT_UN_MERCADO" > 0
  AND f."CAT_R$_MERCADO" BETWEEN 1 AND 3
  AND e.estoque_qtde <= 0                -- remova para ver todos, com e sem estoque
ORDER BY categoria, e.rede
LIMIT 200;
```

Só cruza PDVs das 10 redes que enviam estoque.

#### ⭐ PDVs de uma rede por categoria

**Pergunta frequente.** Identifique os PDVs da rede pela **raiz do CNPJ** (8 primeiros dígitos):
`61585865` = RAIA DROGASIL. Não filtre os PDVs por nome com `ILIKE '%RAIA%'`, que traz farmácias como
"PRAIA GRANDE". Para outra rede, descubra as raízes com
`SELECT DISTINCT left(lpad("CNPJ_PDV"::text, 14, '0'), 8) FROM tdd.dim_pdv WHERE "DESC_PDV" ILIKE '%<nome da rede>%'`
— aqui o `ILIKE` é o certo, porque o cadastro escreve mais do que o usuário fala ("Pague Menos"
está como `FARMACIA PAGUE MENOS`).

**Uma rede pode ter mais de uma raiz de CNPJ** (a Pague Menos tem `06626253` e `04899316` só no
Ceará). Use todas as que a descoberta devolver, com `IN (...)` ou com a própria subconsulta no
lugar do `=`; filtrar por uma só deixa lojas da rede de fora da contagem.

*"Quais são todos os PDVs da Raia Drogasil e a categoria de cada um?"*

```sql
-- C34 · Todos os PDVs da RAIA DROGASIL com a categoria, incluindo SEM CAT
WITH par AS (
  SELECT 3 AS cod_grupo                  -- 3 = Mercado · 2 = Ease Labs
),
periodo AS (
  SELECT MIN(f."COD_PERIODO") AS cod_periodo
  FROM tdd.fato_tdd f, par
  WHERE f."COD_GRUPO" = par.cod_grupo
    AND f."CAT_R$_MERCADO" > 0           -- unidades: f."CAT_UN_MERCADO" > 0
)
SELECT lpad(d."CNPJ_PDV"::text, 14, '0') AS cnpj,
       d."DESC_PDV",
       d."CIDADE_PDV",
       d."UF_PDV",
       p.cod_periodo,
       COALESCE(NULLIF(f."CAT_R$_MERCADO", 0)::text, 'SEM CAT') AS categoria   -- unidades: f."CAT_UN_MERCADO"
FROM tdd.dim_pdv d
CROSS JOIN par
CROSS JOIN periodo p
LEFT JOIN tdd.fato_tdd f
       ON f."COD_PDV" = d."COD_PDV"
      AND f."COD_GRUPO" = par.cod_grupo
      AND f."COD_PERIODO" = p.cod_periodo
WHERE left(lpad(d."CNPJ_PDV"::text, 14, '0'), 8) = '61585865'   -- raiz do CNPJ da RAIA DROGASIL
ORDER BY categoria, d."UF_PDV", d."CIDADE_PDV";
```

*"Quantas lojas da Raia Drogasil existem em cada categoria?"*

```sql
-- C35 · Quantidade de PDVs da RAIA DROGASIL por categoria, incluindo SEM CAT
WITH par AS (
  SELECT 3 AS cod_grupo                  -- 3 = Mercado · 2 = Ease Labs
),
periodo AS (
  SELECT MIN(f."COD_PERIODO") AS cod_periodo
  FROM tdd.fato_tdd f, par
  WHERE f."COD_GRUPO" = par.cod_grupo
    AND f."CAT_R$_MERCADO" > 0           -- unidades: f."CAT_UN_MERCADO" > 0
)
SELECT COALESCE(NULLIF(f."CAT_R$_MERCADO", 0)::text, 'SEM CAT') AS categoria,  -- unidades: f."CAT_UN_MERCADO"
       COUNT(*) AS pdvs,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_pdvs
FROM tdd.dim_pdv d
CROSS JOIN par
CROSS JOIN periodo p
LEFT JOIN tdd.fato_tdd f
       ON f."COD_PDV" = d."COD_PDV"
      AND f."COD_GRUPO" = par.cod_grupo
      AND f."COD_PERIODO" = p.cod_periodo
WHERE left(lpad(d."CNPJ_PDV"::text, 14, '0'), 8) = '61585865'   -- raiz do CNPJ da RAIA DROGASIL
GROUP BY 1
ORDER BY 1;
```

---

## 4. PBM (Programa de Benefício Médico)

O PBM tem três visões. **Identifique qual o usuário quer:**

| Visão | Pergunta típica | Fonte |
|---|---|---|
| **4.1 Adesões** | "Quantos pacientes aderiram ao PBM?", "Quais médicos têm mais adesões?" | `pbm.fato_pbm_adesoes` |
| **4.2 Transações** | "Quantas unidades saíram pelo PBM?", "Em quais PDVs o paciente do médico X comprou?" | `pbm.fato_pbm_transacoes` |
| **4.3 Vouchers** | "Quantos vouchers tivemos no mês?" | `cddd.vw_sell_out` (coluna `pbm`) |

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `pbm.fato_pbm_adesoes` | Pacientes cadastrados no PBM pelo CRM do médico (CRMs adesores) | `"DATA_ADESAO"`, `"MARCA"`, `"EAN"`, `"CAMPANHA"`, `"UF_PROFISSIONAL"`, `"COD_PROFISSIONAL"` (bigint), `"NOME_PROFISSIONAL"`, `"ID_CONSUMIDOR"`, `"CNPJ_PDV"`, `"NOME_FANTASIA"` |
| `pbm.fato_pbm_transacoes` | Compras feitas com desconto do PBM | `"STATUS_TRN"`, `"DATA_REF"`, `"EAN"`, `"MARCA"`, `"CAMPANHA"`, `"DESC_ADM"` (texto, % de desconto), `"QTDE"` (texto), `"QTDE_DEVOLVIDA"` (texto), `"CNPJ_PDV"`, `"NOME_FANTASIA"`, `"CIDADE_PDV"`, `"UF_PDV"`, `"UF_PROFISSIONAL"`, `"COD_PROFISSIONAL"` (texto), `"NOME_PROFISSIONAL"` |
| `cddd.vw_sell_out` | Resultado Ease consolidado; a coluna `pbm` é o **Voucher** | `date`, `cod_ct`, `nome_abreviado_ct`, `cod_gr`, `cod_apres`, `pbm` |
| `cddd.pbm_consolidado` | Origem do Voucher da `vw_sell_out` | `data_ref`, `ean`, `desconto`, `qtde`, `cod_ct`, `cod_gr` |

- **Pergunte o período** antes de qualquer número.
- **Transação válida = `"STATUS_TRN" = 'CONFIRMADA'`.** Os outros status (`PRE`, `PEN`, `ANU`, `CAN`, `CANCELADA`) não são venda e vêm com data `1900-01-01`.
- **CRM:** `"UF_PROFISSIONAL" || lpad("COD_PROFISSIONAL"::text, 7, '0')`. Código `0` = profissional não informado: exclua em rankings por médico.
- **`"MARCA"`** varia de caixa (`ExtratoCannabs` / `EXTRATOCANNABS`): compare com `upper("MARCA")`. `CANABIDIOL` = Isolados; `EXTRATOCANNABS` = Extrato. Para SKU, use `"EAN"`.
- **`"DESC_ADM"`** é o % de desconto em texto (`'25'`, `'25.00'`, `'99.99'`): converta com `::numeric`.
- **Nunca exponha dados do consumidor** (`CPF_CONS`, `NOME_CONS`, `E_MAIL`, `CELULAR`, `TELEFONE`, `DATA_NASC`, endereço do consumidor). Conte pacientes por `"ID_CONSUMIDOR"`.

### 4.1 Adesões

*"Quantas adesões ao PBM tivemos por mês?"*

```sql
-- D01 · Adesões por mês e marca
SELECT date_trunc('month', "DATA_ADESAO")::date AS mes,
       upper("MARCA") AS marca,
       COUNT(*) AS adesoes,
       COUNT(DISTINCT "ID_CONSUMIDOR") AS pacientes
FROM pbm.fato_pbm_adesoes
WHERE "DATA_ADESAO" >= :data_ini AND "DATA_ADESAO" < :data_fim   -- data_fim = 1º dia do mês seguinte
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

*"Quantos médicos geraram adesões no mês?"*

```sql
-- D02 · CRMs adesores por mês
SELECT date_trunc('month', "DATA_ADESAO")::date AS mes,
       COUNT(DISTINCT "UF_PROFISSIONAL" || lpad("COD_PROFISSIONAL"::text, 7, '0')) AS crms_adesores,
       COUNT(*) AS adesoes
FROM pbm.fato_pbm_adesoes
WHERE "COD_PROFISSIONAL" <> 0
  AND "DATA_ADESAO" >= :data_ini AND "DATA_ADESAO" < :data_fim
GROUP BY 1
ORDER BY 1 DESC;
```

*"Quais médicos têm mais adesões?"*

```sql
-- D03 · Ranking de médicos por adesões
SELECT "UF_PROFISSIONAL" || lpad("COD_PROFISSIONAL"::text, 7, '0') AS crm,
       MAX("NOME_PROFISSIONAL") AS nome,
       COUNT(*) AS adesoes,
       COUNT(DISTINCT "ID_CONSUMIDOR") AS pacientes
FROM pbm.fato_pbm_adesoes
WHERE "COD_PROFISSIONAL" <> 0
  AND "DATA_ADESAO" >= :data_ini AND "DATA_ADESAO" < :data_fim
GROUP BY 1
ORDER BY adesoes DESC
LIMIT 50;
```

*"Quantas adesões o médico X gerou?"*

```sql
-- D04 · Adesões de um médico por mês e marca
SELECT date_trunc('month', "DATA_ADESAO")::date AS mes,
       upper("MARCA") AS marca,
       COUNT(*) AS adesoes
FROM pbm.fato_pbm_adesoes
WHERE "UF_PROFISSIONAL" || lpad("COD_PROFISSIONAL"::text, 7, '0') = :crm
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

*"Quais campanhas trazem mais adesões?"*

```sql
-- D05 · Adesões por campanha
SELECT "CAMPANHA",
       COUNT(*) AS adesoes,
       COUNT(DISTINCT "ID_CONSUMIDOR") AS pacientes
FROM pbm.fato_pbm_adesoes
WHERE "DATA_ADESAO" >= :data_ini AND "DATA_ADESAO" < :data_fim
GROUP BY 1
ORDER BY adesoes DESC;
```

### 4.2 Transações

*"Quantas unidades saíram pelo PBM por mês?"*

```sql
-- D10 · Unidades PBM por mês e SKU
SELECT date_trunc('month', "DATA_REF")::date AS mes, "EAN",
       COUNT(*) AS transacoes,
       SUM("QTDE"::int - "QTDE_DEVOLVIDA"::int) AS unidades
FROM pbm.fato_pbm_transacoes
WHERE "STATUS_TRN" = 'CONFIRMADA'
  AND "DATA_REF" >= :data_ini AND "DATA_REF" < :data_fim
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

*"Quantas transações tiveram desconto de 99%?"*

```sql
-- D11 · Transações com desconto de 99% por mês e SKU
SELECT date_trunc('month', "DATA_REF")::date AS mes, "EAN",
       COUNT(*) AS transacoes,
       SUM("QTDE"::int - "QTDE_DEVOLVIDA"::int) AS unidades
FROM pbm.fato_pbm_transacoes
WHERE "STATUS_TRN" = 'CONFIRMADA'
  AND "DESC_ADM"::numeric >= 99                -- desconto de 99% (0,99)
  AND "DATA_REF" >= :data_ini AND "DATA_REF" < :data_fim
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

*"Como se distribuem as transações por faixa de desconto?"*

```sql
-- D12 · Transações por faixa de desconto, por mês
SELECT date_trunc('month', "DATA_REF")::date AS mes,
       CASE WHEN "DESC_ADM"::numeric >= 99 THEN '99%'
            WHEN "DESC_ADM"::numeric >= 70 THEN '70% a 98%'
            ELSE 'Abaixo de 70%' END AS faixa_desconto,
       COUNT(*) AS transacoes,
       SUM("QTDE"::int - "QTDE_DEVOLVIDA"::int) AS unidades
FROM pbm.fato_pbm_transacoes
WHERE "STATUS_TRN" = 'CONFIRMADA'
  AND "DATA_REF" >= :data_ini AND "DATA_REF" < :data_fim
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

*"Em quais PDVs os pacientes do médico X compraram pelo PBM?"*

```sql
-- D13 · PDVs das transações PBM de um médico
SELECT "NOME_FANTASIA", "CNPJ_PDV", "CIDADE_PDV", "UF_PDV",
       SUM("QTDE"::int - "QTDE_DEVOLVIDA"::int) AS unidades,
       MAX("DATA_REF") AS ultima_transacao
FROM pbm.fato_pbm_transacoes
WHERE "STATUS_TRN" = 'CONFIRMADA'
  AND "UF_PROFISSIONAL" || lpad("COD_PROFISSIONAL", 7, '0') = :crm
GROUP BY 1, 2, 3, 4
ORDER BY unidades DESC
LIMIT 20;
```

`"CNPJ_PDV"` tem valores corrompidos (ex.: `4,0007E+13`); nesses casos identifique o PDV por `"NOME_FANTASIA"` e cidade.

*"Quais médicos têm mais unidades no PBM?"*

```sql
-- D14 · Ranking de médicos por unidades PBM
SELECT "UF_PROFISSIONAL" || lpad("COD_PROFISSIONAL", 7, '0') AS crm,
       MAX("NOME_PROFISSIONAL") AS nome,
       SUM("QTDE"::int - "QTDE_DEVOLVIDA"::int) AS unidades
FROM pbm.fato_pbm_transacoes
WHERE "STATUS_TRN" = 'CONFIRMADA'
  AND "COD_PROFISSIONAL" <> '0'
  AND "DATA_REF" >= :data_ini AND "DATA_REF" < :data_fim
GROUP BY 1
ORDER BY unidades DESC
LIMIT 50;
```

### 4.3 Vouchers

**Quando perguntarem "quantos vouchers", use a coluna `pbm` da `cddd.vw_sell_out`.** É o número que
abate o Sell Out Ease Total (seção 2.1).

O Voucher vem da `cddd.pbm_consolidado`, que conta as transações PBM com desconto alto:
- até 2024: desconto de **99% ou mais**, 1 unidade por unidade vendida;
- a partir de 2025: desconto de **70% ou mais**; entre 70% e 80%, cada unidade vale **0,67**.

Por isso o Voucher tem casas decimais (ago/26: 127 unidades a 99% + 93 × 0,67 = **189,31**) e não
bate com a contagem de transações da D11.

*"Quantos vouchers tivemos mês a mês?"*

```sql
-- D20 · Vouchers mês a mês
SELECT date_trunc('month', s.date)::date AS mes,
       ROUND(SUM(s.pbm)::numeric, 2) AS vouchers
FROM cddd.vw_sell_out s
GROUP BY 1
ORDER BY 1 DESC;
```

*"Quantos vouchers cada representante teve no mês?"*

```sql
-- D21 · Vouchers por representante
SELECT s.nome_abreviado_ct AS representante,
       ROUND(SUM(s.pbm)::numeric, 2) AS vouchers
FROM cddd.vw_sell_out s
WHERE s.date >= :data_ini AND s.date < :data_fim
GROUP BY 1
HAVING SUM(s.pbm) > 0
ORDER BY vouchers DESC;
```

*"Quantos vouchers por GR?"*

```sql
-- D22 · Vouchers por GR
SELECT g.nome_gr AS gr,
       ROUND(SUM(s.pbm)::numeric, 2) AS vouchers
FROM cddd.vw_sell_out s
LEFT JOIN cddd.dim_gr g ON g.cod_gr = s.cod_gr
WHERE s.date >= :data_ini AND s.date < :data_fim
GROUP BY 1
ORDER BY vouchers DESC;
```

*"Quantos vouchers de cada produto?"*

```sql
-- D23 · Vouchers por SKU, mês a mês
SELECT date_trunc('month', s.date)::date AS mes,
       a.desc_apresentacao,
       ROUND(SUM(s.pbm)::numeric, 2) AS vouchers
FROM cddd.vw_sell_out s
LEFT JOIN cddd.apres a ON a.cod_apresentacao = s.cod_apres
WHERE s.date >= :data_ini AND s.date < :data_fim
GROUP BY 1, 2
HAVING SUM(s.pbm) > 0
ORDER BY 1 DESC, 3 DESC;
```

---

## 5. Força de Vendas, Painel e Visitas

| Tabela | Conteúdo | Colunas-chave |
|---|---|---|
| `cddd.forca_vendas` | Brick → território → representante | `cod_utc` (bigint), `cod_territorio` (texto, 7 dígitos), `desc_territorio` (nome do representante) |
| `cddd.fv_distrito` / `cddd.fv_territorio` | GR → territórios | `desc_distrito` (nome do GR), `cod_distrito`, `cod_territorio`, `desc_territorio` |
| `cddd.utc` | Brick → cidade, UF e região | `cod_utc`, `desc_utc`, `cidade` (sem acento), `uf`, `regiao` |
| `cddd.scd_ct_territorio` + `cddd.dim_ct` | CT (representante) do território, com e-mail | `cod_territorio`, `cod_setor`, `cod_ct`, `nome_abreviado_ct`, `email_ct`, `data_saida_territorio` |
| `audit.rx_cadastro_mais_recente` | **Painel atual**: médicos atribuídos a cada setor | `crm_link`, `nome`, `setor` (4 dígitos), `setor_cliente` (território), `categoria`, `classificacao`, `potencial`, `frequencia`, `dias_sem_visita`, contatos |
| `audit.trade_cadastro_estabelecimento` | **PDVs visitados** pela força de vendas | `cnpj` (14 dígitos), `setor`, `nome_setor`, `nome_rede`, `nome_loja`, `cidade`, `uf`, `frequencia` |
| `audit.rx_visitas` | **Histórico de visitas a MÉDICOS** | `crm_norm`, `nome`, `setor`, `setor_cliente`, `setor_ims` (nome curto do representante), `data_da_visita`, `visita_efetiva`, `tipo_visita`, `lista_de_motivo_de_nao_visita`, `comentarios` |
| `audit.trade_visita` | **Histórico de visitas a PDVs** (farmácias), desde mai/2023 | `cnpj` (14 dígitos, texto), `data_da_visita` (date), `visita_efetiva` (**boolean**), `lista_de_motivo_de_nao_visita`, `setor`, `setor_cliente` (território, liga à `cddd.forca_vendas`), `setor_ims` (nome curto do representante), `nome_do_setor` (praça), `bandeira` |

- **Visitado = `visita_efetiva = 'S'`.** `'N'` é tentativa sem contato: não conta como visita
  (o motivo está em `lista_de_motivo_de_nao_visita`).
- **Visita a PDV ≠ visita a médico.** "PDVs visitados", "farmácias visitadas", "visitas a lojas"
  vêm da `audit.trade_visita` (seção 5.4). Médico visitado vem da `audit.rx_visitas`. **Nunca conte
  PDV pela `rx_visitas`:** o `cnpj` dela vem vazio em quase todas as linhas, e a contagem dá 1
  (conversa de 2026-09-24: "1 PDV em 480 visitas" — eram visitas a médicos).
- Na `trade_visita`, `visita_efetiva` é **boolean** (`WHERE visita_efetiva`), não `'S'`. Ela é
  só da força de vendas: não tem o setor `3000` de visitação remota.
- **Setor `3000` = Visitação Remota; os demais setores = Força de Vendas.** Se o usuário não disser
  qual dos dois quer, pergunte. Um médico pode ter sido visitado pelos dois.
- **Pergunte o período.** MAT = 12 meses fechados até o mês de referência (MAT 01/07/2026 =
  ago/25 a jul/26); YTD = de janeiro até o mês de referência.
- **Representante pelo nome:** `desc_territorio ILIKE '%primeiro nome%'` na `cddd.forca_vendas`. O
  usuário escreve de várias formas ("Hermes", "Hermes Bizotto"); se voltar mais de um, pergunte qual.
- **`cddd.forca_vendas` é a foto de hoje**, como o painel: só tem quem está no território agora.
  Representante desligado não aparece nela, nem para meses em que ele vendeu. Quem estava em qual
  território, e até quando, está na `cddd.scd_ct_territorio` (`data_saida_territorio`); o
  desligamento, na `cddd.dim_ct` (`data_demissao`). Por isso um nome que "não existe" na força de
  vendas pode existir na `dim_ct` — é o caso de quem saiu.
- **GR:** `cddd.fv_distrito` → `cddd.fv_territorio` (por `cod_distrito`) → `cddd.forca_vendas`
  (por `cod_territorio`).
- `SEM REP` e `SETOR VAGO%` = território sem representante. Os setores `3000` e `1099` não têm
  território na força de vendas.
- `tipo_visita` vazio = **não informado**; não assuma visita presencial.
- **Painel é foto de hoje; visitas são histórico.** Ao cruzar os dois, deixe isso claro na resposta.
- **CRM:** as tabelas do banco já estão no formato UF + 7 dígitos (`MG0039273`). Em listas externas,
  normalize antes de cruzar: só dígitos, sem zeros à esquerda, completar com zeros até 7; no RJ,
  número com mais de 7 dígitos começando em `52` traz o prefixo do conselho, que deve ser retirado.
- Não existe data planejada de próxima visita em nenhuma tabela.

### 5.1 Representantes e hierarquia

*"Quem é o Hermes? Qual o território, o e-mail e o GR dele?"*

```sql
-- E01 · Representante pelo nome, com território, e-mail e GR
SELECT DISTINCT
       fv.cod_territorio,
       btrim(fv.desc_territorio) AS representante,
       ct.nome_abreviado_ct,
       ct.email_ct,
       d.desc_distrito AS gr
FROM cddd.forca_vendas fv
LEFT JOIN cddd.fv_territorio t      ON t.cod_territorio = fv.cod_territorio
LEFT JOIN cddd.fv_distrito d        ON d.cod_distrito = t.cod_distrito
LEFT JOIN cddd.scd_ct_territorio s  ON s.cod_territorio::text = fv.cod_territorio
                                   AND s.data_saida_territorio IS NULL
LEFT JOIN cddd.dim_ct ct            ON ct.cod_ct = s.cod_ct
WHERE fv.desc_territorio ILIKE '%' || :rep || '%';
```

*"Compare o sell out do Hermes Bizotto com o do Ricardo Reis em ago/26"* — os dois nomes
precisam aparecer no resultado, inclusive quem não vendeu.

```sql
-- E27 · Resolver os nomes antes de medir (comparação entre representantes)
WITH pedidos(pedaco) AS (VALUES (:rep_1), (:rep_2)),   -- um pedaço de cada nome
resolvidos AS (
  SELECT p.pedaco,
         btrim(fv.desc_territorio) AS representante,
         fv.cod_territorio,
         ct.nome_abreviado_ct,
         ct.data_demissao
  FROM pedidos p
  LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
         ON fv.desc_territorio ILIKE '%' || p.pedaco || '%'
  LEFT JOIN cddd.dim_ct ct
         ON ct.nome_abreviado_ct ILIKE '%' || p.pedaco || '%'
),
vendas AS (   -- os filtros do fato ficam AQUI, não no LEFT JOIN de baixo
  SELECT f.cod_utc, f.und, fb.desc_sigla_fab
  FROM td.fato_td f
  JOIN cddd.canal dc      ON dc.cod_subcanal = f.cod_subcanal AND dc.desc_canal <> 'HOSPITALAR'
  LEFT JOIN cddd.apres a  ON a.cod_apresentacao = f.cod_apresentacao
  LEFT JOIN cddd.prod pr  ON pr.cod_marca = a.cod_marca
  LEFT JOIN cddd.fab fb   ON fb.cod_fab = pr.cod_fab
  WHERE f.cod_anomes = :anomes
)
SELECT r.pedaco,
       COALESCE(r.representante, r.nome_abreviado_ct) AS representante,
       r.data_demissao,
       SUM(v.und) FILTER (WHERE v.desc_sigla_fab = 'EAS') / 1000 AS unidades_ease,
       SUM(v.und) / 1000                                         AS unidades_mercado,
       ROUND(100 * SUM(v.und) FILTER (WHERE v.desc_sigla_fab = 'EAS')
             / NULLIF(SUM(v.und), 0), 2)                         AS share_ease_pct
FROM resolvidos r
LEFT JOIN cddd.forca_vendas fv2 ON fv2.cod_territorio = r.cod_territorio
LEFT JOIN vendas v              ON v.cod_utc = fv2.cod_utc
GROUP BY 1, 2, 3
ORDER BY 2;
-- Linha com representante nulo = o pedaço não existe em lugar nenhum: nome errado.
-- Linha com data_demissao preenchida e unidades nulas = a pessoa saiu antes do período.
-- Dois nomes para o mesmo pedaço = pergunte qual (BIZZOTO traz um; REIS traz dois).
-- Filtro do fato dentro do LEFT JOIN não filtra nada: ele só deixa a coluna nula
-- e a linha continua entrando na soma. Por isso a CTE `vendas`.
```

*"Quais representantes são da equipe do Gabriel Bastos?"*

```sql
-- E02 · Territórios e representantes de um GR
SELECT d.desc_distrito AS gr,
       t.cod_territorio,
       btrim(t.desc_territorio) AS representante
FROM cddd.fv_distrito d
JOIN cddd.fv_territorio t ON t.cod_distrito = d.cod_distrito
WHERE d.desc_distrito ILIKE '%' || :gr || '%'
ORDER BY representante;
```

*"Quem atende o PDV de CNPJ X?"*

```sql
-- E03 · Representante de um PDV (pelo brick)
SELECT p.cnpj_pdv, p.desc_pdv, p.cidade, p.uf, p.cod_utc,
       fv.cod_territorio,
       btrim(fv.desc_territorio) AS representante
FROM cddd.pdvs p
LEFT JOIN cddd.forca_vendas fv ON fv.cod_utc = p.cod_utc
WHERE lpad(regexp_replace(p.cnpj_pdv, '\D', '', 'g'), 14, '0') = :cnpj;
```

*"Quais representantes estão ativos hoje?"*

```sql
-- E04 · Representantes ativos
SELECT DISTINCT
       fv.cod_territorio,
       btrim(fv.desc_territorio) AS representante,
       ct.nome_abreviado_ct,
       ct.email_ct
FROM cddd.scd_ct_territorio s
JOIN cddd.dim_ct ct ON ct.cod_ct = s.cod_ct
JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
  ON fv.cod_territorio = s.cod_territorio::text
WHERE s.data_saida_territorio IS NULL       -- vigente no território
  AND ct.data_demissao IS NULL              -- não desligado
  AND fv.desc_territorio <> 'SEM REP'
  AND fv.desc_territorio NOT ILIKE '%VAGO%'
  AND ct.nome_abreviado_ct NOT ILIKE '%VAGO%'
ORDER BY representante;
```

*"Quais cidades o Hermes visita?"*

```sql
-- E05 · Cidades visitadas por um representante no período
WITH vis AS (
  SELECT v.crm_norm, COUNT(*) AS visitas, MAX(v.data_da_visita)::date AS ultima
  FROM audit.rx_visitas v
  WHERE v.visita_efetiva = 'S'
    AND v.data_da_visita >= :data_ini AND v.data_da_visita < :data_fim
    AND v.setor_cliente IN (SELECT DISTINCT cod_territorio FROM cddd.forca_vendas
                            WHERE desc_territorio ILIKE '%HERMES%')   -- troque o representante aqui
  GROUP BY 1
)
SELECT COALESCE(c.municipio, m.cidade)                                  AS cidade,
       COALESCE(c.estado, NULLIF(split_part(m.utc_nome, ' / ', 1), '')) AS uf,
       COUNT(*)          AS medicos_visitados,
       SUM(vis.visitas)  AS visitas,
       MAX(vis.ultima)   AS ultima_visita
FROM vis
LEFT JOIN (SELECT DISTINCT ON (crm_link) crm_link, municipio, estado
           FROM audit.rx_cadastro_mais_recente ORDER BY crm_link, setor) c
       ON c.crm_link = vis.crm_norm
LEFT JOIN audit.medico m ON m.crm = vis.crm_norm
GROUP BY 1, 2
ORDER BY visitas DESC;
```

A cidade é a de atendimento do médico visitado (painel atual e, na falta, `audit.medico`).

*"O Hermes visita Viçosa (MG)? Quem visita essa cidade?"*

```sql
-- E06 · Representantes que visitaram médicos de uma cidade no período
SELECT COALESCE(btrim(fv.desc_territorio), v.setor_ims)                 AS representante,
       v.setor,
       COALESCE(c.municipio, m.cidade)                                  AS cidade,
       COALESCE(c.estado, NULLIF(split_part(m.utc_nome, ' / ', 1), '')) AS uf,
       COUNT(*)                   AS visitas,
       COUNT(DISTINCT v.crm_norm) AS medicos,
       MAX(v.data_da_visita)::date AS ultima_visita
FROM audit.rx_visitas v
LEFT JOIN (SELECT DISTINCT ON (crm_link) crm_link, municipio, estado
           FROM audit.rx_cadastro_mais_recente ORDER BY crm_link, setor) c
       ON c.crm_link = v.crm_norm
LEFT JOIN audit.medico m ON m.crm = v.crm_norm
LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
       ON fv.cod_territorio = v.setor_cliente
WHERE v.visita_efetiva = 'S'
  AND v.data_da_visita >= :data_ini AND v.data_da_visita < :data_fim
  AND translate(upper(COALESCE(c.municipio, m.cidade)), 'ÁÀÂÃÉÊÍÓÔÕÚÜÇ', 'AAAAEEIOOOUUC') = translate(upper(:cidade), 'ÁÀÂÃÉÊÍÓÔÕÚÜÇ', 'AAAAEEIOOOUUC')     -- ex.: 'VIÇOSA' (acento ignorado)
  AND COALESCE(c.estado, NULLIF(split_part(m.utc_nome, ' / ', 1), '')) = :uf   -- ex.: 'MG'
  -- AND fv.desc_territorio ILIKE '%HERMES%'   -- só um representante
GROUP BY 1, 2, 3, 4
ORDER BY visitas DESC;
```

Existem cidades com o mesmo nome em UFs diferentes (Viçosa em AL, MG e RN): filtre sempre a UF.
O `translate` remove acentos dos dois lados, porque o painel grava "VIÇOSA" e a `cddd.utc` grava
"VICOSA".

*"A cidade X faz parte do território de qual representante?"*

```sql
-- E07 · Representante responsável pelos bricks de uma cidade
SELECT u.cidade, u.uf,
       btrim(fv.desc_territorio) AS representante,
       fv.cod_territorio,
       COUNT(*) AS bricks
FROM cddd.utc u
JOIN cddd.forca_vendas fv ON fv.cod_utc = u.cod_utc
WHERE translate(upper(u.cidade), 'ÁÀÂÃÉÊÍÓÔÕÚÜÇ', 'AAAAEEIOOOUUC') = translate(upper(:cidade), 'ÁÀÂÃÉÊÍÓÔÕÚÜÇ', 'AAAAEEIOOOUUC')
  AND u.uf = :uf
GROUP BY 1, 2, 3, 4
ORDER BY bricks DESC;
```

Território (E07) e visita (E06) são coisas diferentes: a cidade pode estar no território de um
representante e ter sido visitada por outro, ou não ter visita no período.

### 5.2 Painel

*"O médico X está em qual painel? Quem é o representante dele?"*

```sql
-- E10 · Painel e representante de um médico
SELECT r.crm_link, r.nome, r.setor,
       btrim(fv.desc_territorio) AS representante,
       ct.email_ct,
       r.categoria, r.classificacao, r.potencial, r.frequencia, r.dias_sem_visita
FROM audit.rx_cadastro_mais_recente r
LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
       ON fv.cod_territorio = r.setor_cliente
LEFT JOIN cddd.scd_ct_territorio s
       ON s.cod_territorio::text = r.setor_cliente AND s.data_saida_territorio IS NULL
LEFT JOIN cddd.dim_ct ct ON ct.cod_ct = s.cod_ct
WHERE r.crm_link = :crm;
-- Sem linha = o médico não está em nenhum painel hoje. Mais de uma linha = está em mais de um painel.
```

*"Quais médicos estão no painel do Hermes?"*

```sql
-- E11 · Médicos do painel de um representante
SELECT r.crm_link, r.nome, r.setor, r.categoria, r.dsc_primeira_especialidade AS especialidade,
       r.classificacao, r.potencial, r.frequencia, r.municipio, r.estado
FROM audit.rx_cadastro_mais_recente r
WHERE r.setor_cliente IN (SELECT DISTINCT cod_territorio FROM cddd.forca_vendas
                          WHERE desc_territorio ILIKE '%' || :rep || '%')
ORDER BY r.nome;
```

*"Quantos médicos tem o painel de cada representante?"*

```sql
-- E12 · Tamanho do painel por setor e representante, por potencial
SELECT r.setor,
       btrim(fv.desc_territorio) AS representante,
       COUNT(DISTINCT r.crm_link) AS medicos,
       COUNT(DISTINCT r.crm_link) FILTER (WHERE r.potencial = 'A') AS potencial_a,
       COUNT(DISTINCT r.crm_link) FILTER (WHERE r.potencial = 'M') AS potencial_m,
       COUNT(DISTINCT r.crm_link) FILTER (WHERE r.potencial = 'B') AS potencial_b
FROM audit.rx_cadastro_mais_recente r
LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
       ON fv.cod_territorio = r.setor_cliente
GROUP BY 1, 2
ORDER BY medicos DESC;
```

*"O PDV de CNPJ X é visitado? Por quem?"*

```sql
-- E13 · PDV visitado pela força de vendas e representante responsável
SELECT t.cnpj,
       t.nome_rede,
       t.nome_loja,
       t.cidade,
       t.uf,
       t.setor,
       t.nome_setor,
       t.frequencia,
       btrim(fv.desc_territorio) AS representante,
       ct.email_ct
FROM audit.trade_cadastro_estabelecimento t
LEFT JOIN cddd.scd_ct_territorio s
       ON s.cod_setor = t.setor AND s.data_saida_territorio IS NULL
LEFT JOIN cddd.dim_ct ct ON ct.cod_ct = s.cod_ct
LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
       ON fv.cod_territorio = s.cod_territorio::text
WHERE t.cnpj = lpad(regexp_replace(:cnpj, '\D', '', 'g'), 14, '0');
-- Sem linha = o PDV não está no cadastro de visitação da força de vendas.
```

`audit.trade_cadastro_estabelecimento` é o cadastro de PDVs visitados pela força de vendas: um
CNPJ (14 dígitos, texto) por linha, com o `setor` (4 dígitos) que o visita.

### 5.3 Visitas

*"Quando o médico X foi visitado pela última vez?"*

```sql
-- E20 · Últimas visitas efetivas de um médico
SELECT data_da_visita::date AS data,
       setor,
       setor_ims AS representante,
       COALESCE(tipo_visita, 'Não informado') AS tipo,
       comentarios
FROM audit.rx_visitas
WHERE crm_norm = :crm
  AND visita_efetiva = 'S'
ORDER BY data_da_visita DESC, id_visita DESC
LIMIT 5;
```

*"Quantos médicos únicos foram visitados no MAT, pela força de vendas e pela visitação remota?"*

```sql
-- E21 · Médicos únicos visitados no período, por canal
SELECT CASE WHEN setor = 3000 THEN 'Visitação Remota' ELSE 'Força de Vendas' END AS canal,
       COUNT(DISTINCT crm_norm) AS medicos_visitados,
       COUNT(*) AS visitas_efetivas
FROM audit.rx_visitas
WHERE visita_efetiva = 'S'
  AND data_da_visita >= :data_ini AND data_da_visita < :data_fim   -- MAT 01/07/2026: '2025-08-01' a '2026-08-01'
GROUP BY 1;
```

O total de médicos distintos é menor que a soma dos dois canais, porque um médico pode ter sido
visitado pelos dois. Para o total, rode a mesma query sem o `GROUP BY`.

*"Quantas visitas cada representante fez por mês?"*

```sql
-- E22 · Visitas efetivas por representante e mês (força de vendas)
SELECT date_trunc('month', v.data_da_visita)::date AS mes,
       COALESCE(btrim(fv.desc_territorio), v.setor_ims) AS representante,
       v.setor,
       COUNT(*) AS visitas,
       COUNT(DISTINCT v.crm_norm) AS medicos
FROM audit.rx_visitas v
LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
       ON fv.cod_territorio = v.setor_cliente
WHERE v.visita_efetiva = 'S'
  AND v.setor <> 3000
  AND v.data_da_visita >= :data_ini AND v.data_da_visita < :data_fim
GROUP BY 1, 2, 3
ORDER BY 1 DESC, visitas DESC;
```

*"Qual a cobertura do painel? Quantos médicos do painel foram visitados?"*

```sql
-- E23 · Cobertura do painel atual no período, por setor
WITH visitados AS (
  SELECT DISTINCT crm_norm, setor
  FROM audit.rx_visitas
  WHERE visita_efetiva = 'S'
    AND data_da_visita >= :data_ini AND data_da_visita < :data_fim
)
SELECT r.setor,
       COUNT(DISTINCT r.crm_link) AS medicos_no_painel,
       COUNT(DISTINCT r.crm_link) FILTER (WHERE vi.crm_norm IS NOT NULL) AS medicos_visitados,
       ROUND(100.0 * COUNT(DISTINCT r.crm_link) FILTER (WHERE vi.crm_norm IS NOT NULL)
             / NULLIF(COUNT(DISTINCT r.crm_link), 0), 1) AS pct_cobertura
FROM audit.rx_cadastro_mais_recente r
LEFT JOIN visitados vi ON vi.crm_norm = r.crm_link AND vi.setor = r.setor
GROUP BY 1
ORDER BY pct_cobertura DESC;
```

*"Quais médicos do painel do setor X estão há mais tempo sem visita?"*

```sql
-- E24 · Painel de um setor com a última visita efetiva
SELECT r.crm_link, r.nome, r.categoria, r.potencial,
       MAX(v.data_da_visita)::date AS ultima_visita,
       (SELECT MAX(data_da_visita)::date FROM audit.rx_visitas) - MAX(v.data_da_visita)::date AS dias_desde,
       COUNT(v.id_visita) AS visitas_efetivas
FROM audit.rx_cadastro_mais_recente r
LEFT JOIN audit.rx_visitas v
       ON v.crm_norm = r.crm_link AND v.setor = r.setor AND v.visita_efetiva = 'S'
WHERE r.setor = :setor
GROUP BY 1, 2, 3, 4
ORDER BY ultima_visita NULLS FIRST;
```

`dias_desde` conta a partir da data mais recente da base de visitas. Médico sem visita aparece
primeiro, com `ultima_visita` vazia.

*"Por que as visitas não acontecem?"*

```sql
-- E25 · Tentativas sem contato por motivo
SELECT COALESCE(lista_de_motivo_de_nao_visita, 'Não informado') AS motivo,
       COUNT(*) AS tentativas,
       COUNT(DISTINCT crm_norm) AS medicos
FROM audit.rx_visitas
WHERE visita_efetiva = 'N'
  AND data_da_visita >= :data_ini AND data_da_visita < :data_fim
GROUP BY 1
ORDER BY tentativas DESC;
```

*"Quantas visitas foram por telefone, WhatsApp ou vídeo?"*

```sql
-- E26 · Visitas efetivas por tipo de contato
SELECT CASE WHEN setor = 3000 THEN 'Visitação Remota' ELSE 'Força de Vendas' END AS canal,
       COALESCE(tipo_visita, 'Não informado') AS tipo,
       COUNT(*) AS visitas
FROM audit.rx_visitas
WHERE visita_efetiva = 'S'
  AND data_da_visita >= :data_ini AND data_da_visita < :data_fim
GROUP BY 1, 2
ORDER BY 1, visitas DESC;
```

### 5.4 Visitas a PDV

Rede, loja e cidade do PDV vêm da `audit.trade_cadastro_estabelecimento` pelo `cnpj` (~90% casam;
nas demais, a `bandeira` da visita). "Semana passada" = segunda a domingo antes da semana da
última data da base.

*"Quantos PDVs foram visitados semana passada?"*

```sql
-- E28 · PDVs visitados no período (força de vendas)
SELECT COUNT(DISTINCT v.cnpj) AS pdvs_visitados,
       COUNT(*)               AS visitas_efetivas,
       COUNT(DISTINCT v.setor) AS setores
FROM audit.trade_visita v
WHERE v.visita_efetiva
  AND v.data_da_visita >= :data_ini AND v.data_da_visita < :data_fim;   -- semana: segunda a segunda
```

*"Quantos PDVs cada representante visitou no mês?"*

```sql
-- E29 · PDVs visitados por representante no período
SELECT COALESCE(btrim(fv.desc_territorio), v.setor_ims) AS representante,
       v.setor,
       COUNT(DISTINCT v.cnpj) AS pdvs_visitados,
       COUNT(*)               AS visitas_efetivas
FROM audit.trade_visita v
LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
       ON fv.cod_territorio = v.setor_cliente
WHERE v.visita_efetiva
  AND v.data_da_visita >= :data_ini AND v.data_da_visita < :data_fim
GROUP BY 1, 2
ORDER BY pdvs_visitados DESC;
```

*"Quando a farmácia X foi visitada? Quem visitou?"*

```sql
-- E30 · Últimas visitas a um PDV
SELECT v.data_da_visita AS data,
       CASE WHEN v.visita_efetiva THEN 'efetiva' ELSE 'sem contato' END AS situacao,
       v.lista_de_motivo_de_nao_visita AS motivo,
       COALESCE(btrim(fv.desc_territorio), v.setor_ims) AS representante,
       COALESCE(t.nome_rede, v.bandeira) AS rede,
       t.nome_loja,
       t.cidade,
       t.uf
FROM audit.trade_visita v
LEFT JOIN audit.trade_cadastro_estabelecimento t ON t.cnpj = v.cnpj
LEFT JOIN (SELECT DISTINCT cod_territorio, desc_territorio FROM cddd.forca_vendas) fv
       ON fv.cod_territorio = v.setor_cliente
WHERE v.cnpj = lpad(regexp_replace(:cnpj, '\D', '', 'g'), 14, '0')
ORDER BY v.data_da_visita DESC
LIMIT 10;
```
