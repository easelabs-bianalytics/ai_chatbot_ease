# ADR-0016: OpenAI GPT-5.6 Terra para planejar e Luna para redigir (substitui ADR-0013)

## Status
Aceito — 2026-09-17. Substitui ADR-0013 (OpenAI GPT-4o).

## Contexto
O ADR-0013 registrou "GPT 4.0" (`gpt-4o`) porque era o que o usuário tinha
pedido na descoberta, antes de o documento de referência ser reescrito. Com
as 96 consultas e as regras de negócio do documento atual, o trabalho da IA
mudou de patamar: ela precisa aplicar dezenas de regras que se contradizem
fora de contexto (três cenários de sell-out, filtros do CDD que mudam com a
data, categoria de PDV cujo período depende do grupo e da coluna, SEM CAT,
raiz de CNPJ, arredondamento de 0,89). O `gpt-4o` é de maio de 2024 e ficou
para trás nesse tipo de tarefa — além de ter ficado mais caro que modelos
melhores.

Comparação levantada em 2026-09-17, com os benchmarks públicos:

| | Claude Sonnet 5 | GPT-5.6 Terra |
|---|---|---|
| Terminal-Bench 2.1 | 80,4% | 87,4% |
| SWE-bench Pro | 63,2% | 63,4% |
| Entrada / saída (US$/milhão) | 2 / 10 | 2 / 12 |
| Leitura de cache | 0,20 | 0,20 |

Nenhum dos dois publica nota de texto-para-SQL, e os benchmarks públicos
dessa tarefa (BIRD, Spider 2.0) têm taxas de erro de anotação de 52,8% e
66,1% (CIDR/VLDB 2026) — não servem para decidir. Custo e capacidade ficaram
tecnicamente empatados.

O desempate foi operacional: o Bedrock exigiria liberação de modelo e de
IAM por quem administra a conta AWS (conferido em 2026-09-17: o usuário
`rubens` recebe `AccessDenied` até para listar modelos no Bedrock), enquanto
a chave da OpenAI o próprio usuário gera na hora.

## Decisão
1. **Planejamento (escrever o SQL): `gpt-5.6-terra`.** É a etapa em que o
   erro é caro e invisível — uma consulta errada roda e devolve um número
   real do recorte errado.
2. **Redação da resposta: `gpt-5.6-luna`** (US$ 0,20/1,20 por milhão). A
   tarefa é reescrever o resultado em português; a ancoragem numérica
   (ADR-0010) cobre o risco.
3. Os dois ficam em variáveis (`AI_PROVIDER_MODEL`, `AI_ANSWER_MODEL`):
   trocar de modelo, inclusive para o Terra nas duas etapas ou para outro
   fornecedor, é mudança de configuração.
4. Saída estruturada (JSON schema) nas duas chamadas, cache de prefixo por
   seção (ADR-0015) e `RetryingAIProvider` com backoff.
5. **Teto de gasto mensal configurável:** o custo de cada resposta já é
   registrado; ao atingir o teto a IA responde que o limite do mês foi
   alcançado, em vez de continuar gastando.
6. O identificador exato dos modelos é conferido na API (`GET /v1/models`)
   na primeira execução da Fase 5, antes de fixar no `.env`.

## Consequências
- Custo **medido** em 2026-09-17, com os cortes do ADR-0015: US$ 0,041 por
  pergunta, ou ~R$ 125 por mês com 25 perguntas por dia (contra ~R$ 500 do
  desenho anterior com `gpt-4o` e o documento inteiro no prompt).
- A tabela de preços de `openai_provider.py` é calibrada pela fatura, não
  pela página publicada: com US$ 2,00 de entrada no Terra o relatório dava
  US$ 0,955 e o painel da OpenAI marcava US$ 1,16; com US$ 2,50 fecha. Toda
  divergência entre fatura e relatório manda reconferir a tabela, porque
  preço subestimado vira teto de gasto que não segura nada.
- **A aplicação no ECS vai precisar de saída para a internet (NAT) para
  chamar a OpenAI.** Isso continua aberto no D-02 e agora é requisito, não
  detalhe. Com o Bedrock não seria necessário.
- Fatura e contrato separados da AWS, com a chave guardada no Secrets
  Manager em produção e no `bi/.env` em desenvolvimento.
- A decisão é reversível: o `AIProvider` é abstrato (ADR-0005), então o
  Bedrock entra como uma classe nova se a liberação da AWS sair ou se a
  suíte mostrar vantagem do Claude.
- A escolha é confirmada por medição, não por benchmark de terceiro: a prova
  de fogo de 20 casos difíceis (~R$ 10) roda antes de fechar a Fase 5.
