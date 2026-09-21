# Banco de perguntas para testar o chatbot de BI

Perguntas difíceis, com a resposta certa conferida no banco AWS em **21/09/2026**. Os números
mudam conforme as bases são atualizadas: o que deve ser avaliado é o **comportamento** (qual fonte
usou, o que perguntou de volta, o que recusou) e a ordem de grandeza.

Como pontuar cada pergunta:

| Nota | Critério |
|---|---|
| ✅ Passou | Número certo (ou pergunta de volta, quando é o esperado) e fonte correta |
| ⚠️ Parcial | Número certo, mas sem o alerta necessário (data da base, fonte, ressalva) |
| ❌ Falhou | Número errado, fonte errada, ou respondeu "não encontrei" quando havia dado |

---

## 1. Identidade: nomes, grafias e pessoas desligadas

**P1.** *"Compare o sell out do Ricardo Reis e do Hermes Bizotto em agosto/26, em unidades."*
- **Testa:** grafia diferente (`HERMES BIZZOTO` na força de vendas) e pessoa desligada.
- **Esperado:** achar o Hermes mesmo com a grafia errada; avisar que **Ricardo Reis saiu em 18/05/2026** (última venda em mai/26) e perguntar se era o **Ricardo Bastos**.
- **Resposta certa:** Hermes 459 un. (CDD ago/26); Ricardo Bastos 276 un.
- **Erro típico:** responder "a consulta não retornou nenhuma linha".

**P2.** *"Quantos médicos a Simone visitou no último trimestre?"*
- **Testa:** nome que não está na força de vendas (a Simone é a Visitação Remota, setor 3000).
- **Esperado:** não achar "Simone" como representante e perguntar se é o painel da Visitação Remota (setor 3000).
- **Erro típico:** devolver zero.

**P3.** *"Qual o CRM e a última visita do Wilson Lopes?"*
- **Testa:** busca de médico por nome, não por CRM.
- **Resposta certa:** MG0039273, WILSON DOS SANTOS LOPES, última visita efetiva em **20/07/2026**, painel do setor 2512.

---

## 2. Números que se parecem, mas não são o mesmo

**P4.** *"Quantas unidades a Ease vendeu em agosto/26?"*
- **Testa:** escolher a fonte certa entre três números possíveis.
- **Resposta certa:** **7.562** (total: CDD + extras + MP + SS − Voucher) ou **7.175** se a pergunta for de CDD. Nunca 7.766, que é a `fato_cdd` sem os filtros.
- **Esperado:** dizer qual dos dois está mostrando.

**P5.** *"Quantos vouchers tivemos em agosto/26?"*
- **Resposta certa:** **189,31** (coluna `pbm` da `vw_sell_out`).
- **Testa:** não confundir com as **127** transações de 99% de desconto; as 93 transações entre 70% e 80% entram com peso 0,67.

**P6.** *"Qual o market share da Ease no varejo em agosto/26?"*
- **Resposta certa (faturamento):** **10,51%**, com R$ 3,34 mi de R$ 31,8 mi. Prati-Donaduzzi lidera com 29,75%.
- **Testa:** dividir por 1000, excluir HOSPITALAR e chegar ao laboratório por `apres → prod → fab`.
- **Erro típico:** responder em bilhões (sem dividir por 1000).

**P7.** *"Quantas unidades Ease o Hermes vendeu em agosto/26 e qual o share dele?"*
- **Testa:** não misturar as duas bases numa coluna só.
- **Resposta certa:** Sell Out Ease (`vw_sell_out`) 459 un.; no mercado varejo (TD) são 458 un. de 2.203, share de **20,79%**.

**P8.** *"Quanto o Hermes vendeu nos últimos 90 dias?"*
- **Testa:** contar a partir da data máxima da base, não de hoje.
- **Esperado:** citar a data de corte da base (17/09/2026, na conferência). O total da companhia no período foi 20.657 un. CDD.

---

## 3. Granularidade que não existe

**P9.** *"Quantas prescrições Ease tivemos no dia 15 de julho?"*
- **Esperado:** explicar que a prescrição é **mensal** (competência no dia 1) e oferecer o mês.

**P10.** *"Quantas prescrições do Isolado de 10 mL tivemos em agosto?"*
- **Esperado:** explicar que a prescrição separa só **Extrato × Canabidiol**, não por SKU, e oferecer o total de Canabidiol.

**P11.** *"Qual o estoque da Ease no CD da Raia hoje?"*
- **Testa:** o estoque é snapshot por rede, e a Raia está em **27/08/2026**.
- **Esperado:** dar o número com a data da carga, não dizer "hoje".

**P12.** *"Quantas unidades o PDV X vendeu de extras no mês?"*
- **Esperado:** explicar que vendas extras, MP e SS **não existem por PDV**; por PDV só há CDD.

---

## 4. Perguntas ambíguas (a IA deve perguntar antes)

**P13.** *"Quantas prescrições o Hermes teve em agosto?"*
- **Esperado:** perguntar se é o **painel** dele ou o **território**.
- **Resposta certa:** painel **157** PX; território **307** PX.

**P14.** *"Qual a categoria do PDV de CNPJ 61412110070870?"*
- **Esperado:** perguntar **Mercado ou Ease Labs** e **unidades ou faturamento**.
- **Resposta certa (Mercado):** categoria **6** em faturamento (TRIM01_202506) e **3** em unidades (SEM01_202601). No período mais recente, a categoria de faturamento do Mercado vem zerada e não deve ser usada.

**P15.** *"Qual o faturamento do mercado em agosto/26?"*
- **Esperado:** perguntar se é **varejo, mercado público ou total**.
- **Resposta certa:** varejo R$ 31,8 mi; mercado público (HOSPITALAR) R$ 11,7 mi.

**P16.** *"Quais CDs estão em ruptura?"*
- **Esperado:** pedir o SKU, ou mostrar SKU a SKU, nunca somando os produtos.
- **Resposta certa (Extrato):** **31 CDs em ruptura** de 44, pela régua `dde_base <= 15` no dia 0.

---

## 5. Ausência de dado (não pode inventar)

**P17.** *"O representante bateu a meta em agosto?"*
- **Esperado:** dizer que a informação de meta ainda não está disponível na base e se oferecer para mostrar o resultado de vendas. O schema `remuneracao_fv` ainda não existe no AWS.

**P18.** *"Qual o estoque da Drogaria Pacheco da rua X?"* (CNPJ de PDV fora das 10 redes)
- **Esperado:** "não há informação de estoque para esse PDV", nunca "estoque zero". Das 18.026 lojas do cadastro, só **7.477** enviam estoque.

**P19.** *"Quando é a próxima visita programada do médico X?"*
- **Esperado:** explicar que não existe data planejada de visita em nenhuma base.

**P20.** *"Quantas unidades da Prati-Donaduzzi foram dispensadas no PDV de CNPJ X?"*
- **Esperado:** explicar que a dispensação por PDV (`fato_cdd`) é só Ease; concorrente existe só no mercado (TD), por brick.

---

## 6. Cruzamentos difíceis

**P21.** *"Quais as 3 cidades onde mais vendemos no território do Hermes no último trimestre?"*
- **Resposta certa:** Belo Horizonte 447, Betim 350, Teófilo Otoni 144 (unidades CDD).

**P22.** *"O Hermes visita Viçosa, em Minas?"*
- **Testa:** acento ("VIÇOSA" no painel × "VICOSA" na `cddd.utc`) e cidade homônima (AL, MG, RN).
- **Resposta certa:** Viçosa-MG está no território do **Ricardo Bastos**, com 24 visitas efetivas no MAT. Não é do Hermes.

**P23.** *"Quantos médicos únicos visitamos no MAT 01/07?"*
- **Resposta certa:** **5.298** no total, sendo 4.954 da força de vendas e 349 da Visitação Remota.
- **Testa:** a soma dos dois canais (5.303) é maior que o total, porque 5 médicos foram visitados pelos dois.

**P24.** *"Quantas lojas da Raia estão em cada categoria de faturamento do mercado?"*
- **Resposta certa:** 3.102 lojas — 43 na categoria 1, 164 na 2, 266 na 3, 342 na 4, 407 na 5, 489 na 6, 547 na 7, 676 na 8 e **168 SEM CAT**.
- **Testa:** incluir as lojas sem categoria em vez de descartá-las.

**P25.** *"Quem são os 5 médicos que mais prescreveram Ease em agosto e quantas unidades saíram no PBM deles?"*
- **Testa:** cruzar prescrição (`audit`) com PBM pelo CRM montado (`UF` + `COD_PROFISSIONAL` com zeros).
- **Referência:** o MG0039273 teve 51 PX e 121 unidades no PBM em ago/26.

**P26.** *"Qual o RX per capita da Ease em agosto?"*
- **Resposta certa:** **1,81** (5.343 PX ÷ 2.959 médicos prescritores).

**P27.** *"O PDV de CNPJ 00285753014060 é visitado? Por quem?"*
- **Resposta certa:** sim, Venancio de Ipanema, setor 2711, representante **Viviane Souza**.
- **Testa:** usar a `audit.trade_cadastro_estabelecimento`.

**P28.** *"Quantos médicos do painel do setor 1111 estão há mais de 90 dias sem visita?"*
- **Testa:** cruzar painel atual com histórico de visitas e contar os dias a partir da data máxima da base.

**P29.** *"Quantas adesões ao PBM tivemos em agosto e quantos médicos geraram adesão?"*
- **Resposta certa:** **3.071 adesões** de **1.980 CRMs**.
- **Testa:** não confundir adesão (paciente) com transação (compra) — foram 7.095 unidades transacionadas no mesmo mês.

**P30.** *"Qual o top 10 de médicos por unidades no PBM em agosto?"*
- **Testa:** excluir o profissional não informado (`COD_PROFISSIONAL = '0'`), que soma 154 das 7.101 unidades do mês.

---

## Perguntas-armadilha extras

| Pergunta | O que deve acontecer |
|---|---|
| *"Quantos médicos estão na categoria 1?"* | Perguntar o período da categoria e oferecer os disponíveis (trimestre, quadrimestre, semestre móvel, YTD, MAT) |
| *"Qual o CNPJ da loja que mais vendeu?"* + *"e o estoque dela?"* | Manter o contexto do CNPJ entre as duas perguntas |
| *"Quanto a Ease cresceu de julho para agosto?"* | Usar a mesma fonte nos dois meses e citar qual |
| *"Quantas unidades vendemos em setembro/26?"* | Avisar que o mês está **incompleto** (base até 17/09 na conferência) |
| *"Qual o estoque de Extrato da DPSP e da Raia?"* | Dar cada número com a **data da carga da rede** (DPSP 14/09 e Raia 27/08 na conferência) |
