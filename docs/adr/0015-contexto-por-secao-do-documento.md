# ADR-0015: contexto montado por seção, e não o documento inteiro

## Status
Aceito — 2026-09-17.

## Contexto
O ADR-0014 manda injetar no prompt o arquivo de referências inteiro, o
catálogo e o snapshot do schema. Depois que o time de BI reescreveu o
documento (96 consultas, 5 seções), isso virou ~45 mil tokens de
referências e ~13 mil de schema em **toda** pergunta, nas duas chamadas ao
modelo: ~60 mil tokens para planejar e ~48 mil para redigir.

Numa pergunta de estoque, o modelo recebe as regras de prescrição, PBM,
sell-out e visitas sem usar nenhuma delas. A conta ficou em torno de
US$ 170 por mês com 25 perguntas por dia no modelo mais forte, quase tudo
pago para enviar texto irrelevante. Decisão do usuário em 2026-09-17:
reduzir o custo antes de escolher o modelo.

O usuário também informou que **perguntas que cruzam áreas são frequentes**
("prescrição e sell-out no território do Hermes"), o que impede um recorte
ingênuo de uma seção por pergunta.

## Decisão
O contexto do planejador passa a ser montado por pergunta, em quatro
partes:

1. **Núcleo comum (~2 mil tokens), sempre enviado:** as regras que valem
   para todo o documento (não inventar dado que não existe, perguntar o
   período, cordialidade no "não disponível"), o glossário dos cinco temas
   e o mapa de ligações entre eles (brick → território → GR, PDV → brick,
   CRM → painel). É ele que permite à IA perceber que a pergunta toca outra
   área.
2. **Os dois primeiros temas completos:** tabelas, regras e consultas de
   referência (as seções têm de 2 a 7 mil tokens cada).
3. **Do terceiro tema em diante, o resumo:** tabelas e regras, sem as
   consultas.
4. **Snapshot filtrado (~2,5 mil tokens):** só as tabelas das seções
   enviadas.

O tema sai de um roteador por palavra-chave (`context.py`), determinístico e
sem chamada de modelo: acrescentar uma chamada antes de toda pergunta seria
mais uma coisa para falhar, custar e demorar. Na dúvida ele inclui a seção a
mais, e sem tema reconhecido manda o documento inteiro. **Errar incluindo custa centavos; errar excluindo custa um número
errado.**

A chamada de redação deixa de receber o documento: vai a pergunta, a
consulta executada, o resultado e as poucas regras de texto do
`answerer_v1.md` (~3 mil tokens).

Quando a primeira tentativa falha (guard recusa, banco erra, IA declara que
não sabe), a correção única do ADR-0014 é feita **com o documento inteiro**,
sem recorte.

**Correção de rumo em 2026-09-17, com medição.** A primeira versão mandava
só a seção principal completa e as vizinhas resumidas. Na primeira pergunta
real que cruzava áreas ("no território do Hermes, quanto prescreveram e
quanto foi dispensado"), a IA usou a saída `PRECISO DA SEÇÃO` e a segunda
chamada custou 44 mil tokens e 80 segundos — US$ 0,14 e 102 segundos no
total. Mandar o segundo tema completo desde o início custa cerca de 3 mil
tokens a mais e evitou o atalho: a mesma pergunta passou a custar US$ 0,04
em 34 segundos. O resumo continua valendo do terceiro tema em diante.

## Consequências
- A entrada cai de ~60 mil para ~14 a 18 mil tokens por pergunta, e o custo
  para cerca de um terço. Isso muda a escolha do modelo: o mais capaz passa
  a caber no orçamento.
- O risco muda de lugar: em vez de custo, passa a ser **regra ausente**. Um
  recorte errado faz a IA não ver uma regra que existia. As proteções são o
  núcleo comum, a inclusão generosa de seções e o reenvio do documento
  inteiro na correção.
- **O corte precisa ser medido, não presumido:** a suíte de casos
  (`run_synthetic_cases`) roda com o documento inteiro e com o contexto
  recortado, e a taxa de acerto por seção decide se o corte fica. Os casos
  que cruzam áreas passam a ser parte obrigatória da suíte.
- O `catalog_hash` continua cobrindo o documento inteiro: o que muda é o que
  se envia ao modelo, não o que se considera conhecimento aprovado.
- O cache do provedor passa a ser por seção, e não um prefixo único. Cada
  seção tem seu prefixo estável; perguntas seguidas do mesmo tema aproveitam.
- O `AICall` passa a registrar quais seções foram enviadas, para que o
  relatório mostre custo por tema e denuncie classificação errada.
