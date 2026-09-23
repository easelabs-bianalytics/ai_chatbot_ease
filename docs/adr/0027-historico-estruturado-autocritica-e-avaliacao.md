# ADR-0027: Histórico estruturado, autocrítica do seguimento e avaliação das respostas

## Status
Aceito — 2026-09-23.

## Contexto
Lendo as conversas de produção de 2026-09-23 (conversas 14 e 15), o erro que
mais apareceu foi "não entendeu o contexto":

- **Conversa 15:** a pessoa pediu "considere Extras, MP, SS e Voucher também".
  O planejador repetiu a consulta anterior, devolveu os mesmos 4.306 × 4.716 e
  a redação escreveu que tinha considerado tudo. O histórico levava só os
  primeiros 1.200 caracteres do SQL de cada resposta; a B17 tem uns 2.600, e o
  planejador viu metade dela.
- **Conversa 14:** "quero ver CAT 1 e CAT 3 de forma separada" refez a mesma
  consulta e devolveu o mesmo gráfico.
- **Descoberta de erro:** um erro só aparecia quando alguém lia as conversas no
  banco à mão. Não havia como medir se o Jarvis estava melhorando.
- **Espera:** a tela mostrava "Pensando…" por 10 a 170 s, sem dizer o que o
  Jarvis tinha entendido do pedido.

Regras específicas para cada incidente não escalam. As defesas precisavam ser
genéricas, baratas e deterministas sempre que possível.

## Decisão

### 1. Histórico em campos, não em SQL cortado
Cada resposta anterior vai ao planejador como um resumo (`ai_orchestrator/resumo.py`):

- o que foi entendido e o que não foi atendido;
- a referência e as tabelas;
- os filtros (`WHERE` e `HAVING` de todos os níveis, extraídos pelo `sqlglot`);
- as datas citadas no SQL;
- as colunas e as primeiras linhas do resultado;
- o gráfico.

A **última resposta com dado** leva também o SQL inteiro, até 6 mil
caracteres, porque é dela que o seguimento quase sempre parte. As mais antigas
levam só o resumo.

### 2. Autocrítica do seguimento
O plano ganha o campo `seguimento`, com um destes valores: `muda_o_dado`,
`so_apresentacao`, `repete` ou vazio. A conferência (`autocritica.py`) é
determinista e só compara números:

- **Quando dispara:** o planejador disse `muda_o_dado` e o resultado repete,
  linha a linha, os números da consulta da resposta anterior, com o mesmo
  total de linhas. O nome da coluna não conta.
- **Segunda chance:** nesse caso, o planejador recebe uma nova chamada, na
  etapa `self_check`, com o aviso de que o pedido não foi atendido.
- **Nova consulta com números diferentes:** vale a nova.
- **Consulta mantida, falha ou sem linhas:** fica a primeira. A redação recebe
  em `pedido_nao_atendido` que o número não mudou, e por quê.

Pedido só de apresentação e "refaça" devolvem os mesmos números de propósito:
não disparam nada nem custam nada a mais.

### 3. O que o Jarvis entendeu aparece enquanto ele pensa
O progresso (`progresso.py`) passa a guardar a etapa (`entendi`, `consultando`,
`escrevendo`, `investigando`, `conferindo`) e o entendimento. A tela mostra
"Entendi: …" e a etapa em que o Jarvis está, pelo mesmo polling de sempre. A
resposta aparecendo aos poucos (streaming) fica para depois: exige mudar o
Celery e a tela, e a maior parte do ganho na espera vem daqui.

### 4. Várias consultas por resposta (ADR-0026, ponto B, implementado)
O plano ganha `consultas` (título, SQL, referência), no máximo 4.

- **Duas ou mais consultas:** vão por `_entregar_varias`. Cada uma é validada
  e executada, e a que falhar ganha uma correção própria.
- **Entrega sem dado:** é dita na resposta.
- **Redação:** é uma só, no modelo barato. Toda entrega com dado aparece: a
  que a redação não apontar ganha uma tabela no fim.
- **Uma consulta só, ou planilha anexada:** segue o caminho comum.

### 5. 👍/👎 viram casos de validação
- **Registro:** `messaging.Avaliacao` guarda uma avaliação por resposta, com
  a nota e "o que estava errado". Na tela, os botões ficam embaixo de cada
  resposta; o 👎 é gravado na hora e o comentário completa depois.
- **Rascunho de caso:** `manage.py casos_do_uso` transforma cada 👎 ainda não
  exportado em rascunho em `app/knowledge/casos_do_uso.yaml`, com a pergunta,
  as perguntas anteriores, a referência usada e uma nota com o comentário, a
  resposta e o SQL.
- **Rascunho fora da suíte:** a suíte lê esse arquivo junto com
  `casos_validacao.yaml`, mas rascunho (`rascunho: true`) só roda com
  `--com-rascunhos`. Quem revisa ajusta o esperado, acrescenta as regras e
  tira a marca.
- **Relatório:** o `bi_report` passa a mostrar a taxa de reescrita, as
  segundas chances e as avaliações.

### 6. Menos reescrita, primeiro pelo prompt
26% das redações citavam número que não estava no resultado. O planejador
passa a ser instruído a trazer prontas as colunas que a resposta vai citar
(variação, share, total, posição). Subir o esforço do modelo da redação fica
para depois de medir o efeito disso no `bi_report`.

## Consequências
- O contexto do planejador cresce um pouco na última resposta (o SQL inteiro)
  e diminui nas anteriores, que passam a levar só o resumo.
- A autocrítica custa uma chamada ao planejador só quando dispara, e fica
  registrada no Admin (`raw_response.autocritica`, etapa `self_check`).
- Duas migrações: `ai_orchestrator.0006` (etapa nova) e `messaging.0006`
  (tabela `Avaliacao`).
- O 👎 só vira teste depois de revisado. Um caso ruim não entra na suíte por
  engano, e o custo é alguém do time de BI olhar os rascunhos.
