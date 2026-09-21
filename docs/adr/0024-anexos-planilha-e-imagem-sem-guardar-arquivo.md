# ADR-0024: Anexos — planilha para preencher e imagem para ler, sem guardar o arquivo

## Status
Aceito — 2026-09-21.

## Contexto
Dois pedidos do time, os dois com o mesmo medo por trás — o custo:

1. **Mandar uma planilha e pedir que o Jarvis a preencha** com dado do banco
   (ex.: a lista de redes com a coluna de sell-out de agosto em branco).
2. **Mandar um print e pedir uma análise** do que está nele.

O risco de custo é real e tem nome. Uma planilha de 20 mil linhas enviada
inteira ao modelo seriam 1 a 2 milhões de tokens: US$ 2 a 4 por pergunta,
contra os ~US$ 0,04 de hoje. E um print de tela cheia custa três vezes mais
que o mesmo print reduzido.

Os dois também esbarram em garantias que o projeto já tem: a ancoragem
numérica (ADR-0010) exige que todo número da resposta venha do banco, e a
proteção contra injeção (ADR-0021) olhava só texto.

## Decisão

### O arquivo nunca é guardado
Os bytes ficam no Redis da própria task (o cache do Django, banco `/1`,
separado da fila do Celery), com prazo: 15 minutos para a entrada, 30 para a
planilha preenchida. São descartados assim que a resposta sai — com sucesso
ou com falha. O upload fica só em memória (`FILE_UPLOAD_MAX_MEMORY_SIZE`),
sem arquivo temporário em disco. Não há S3, volume nem coluna com conteúdo.

A mensagem guarda só a etiqueta: tipo, nome, o resumo que subiu ao modelo e
o token do depósito. A conversa mostra "você enviou `metas.xlsx`" para
sempre; o arquivo em si deixa de existir.

### Planilha: sobe a forma, nunca o conteúdo
`attachments/planilha.py` lê com `read_only=True` e `data_only=True` (sem
avaliar fórmula) e produz um resumo: abas, número de linhas, e por coluna o
nome, o tipo inferido e até dois exemplos das oito primeiras linhas. Teto de
4.000 caracteres (~1.000 tokens). No teste real: **212 caracteres**.

O planejador recebe esse resumo e devolve, além do SQL, **quatro nomes de
coluna** (`preenchimento`): a chave e o destino na planilha, a chave e o
valor no resultado. Nunca valores.

Quem escreve nas células é o `openpyxl`, com o resultado da consulta. A
consulta roda de novo com limite de 50 mil linhas (o mesmo do download), já
que a que respondeu vem cortada em 500 — o que o modelo lê.

O casamento das linhas é regra nossa, sem token:
1. idêntico depois de normalizar caixa, acento e espaço;
2. **nome contido, e só se for único** ("Drogasil" → "RAIA DROGASIL").
   Se duas chaves do banco servirem, nenhuma serve.

Chave repetida no resultado fica em branco. A resposta lista, pelo nome, o
que casou por aproximação (para conferir) e o que ficou em branco (para
corrigir). Texto vindo do banco que começaria com `=`, `+`, `-` ou `@` vira
texto explícito, nunca fórmula.

### Imagem: modelo barato, prompt curto, rótulo explícito
`attachments/imagem.py` valida pelo conteúdo (Pillow), não pela extensão, e
reduz o maior lado para 1.280 px. PNG na saída: o custo depende da área, não
dos bytes, e JPEG borraria o texto pequeno do print.

A leitura é **uma chamada** ao `gpt-5.6-luna` (um décimo do preço do
planejador), com um prompt próprio de ~350 tokens — sem catálogo, schema ou
consultas de referência. Não passa pelo planejador nem pelo banco.

Sem consulta não há ancoragem. O que a substitui é o **rótulo**: a resposta
começa dizendo que aquilo veio da imagem, não do banco da Ease Labs, e a
decisão é própria (`image_reading`), separada de "respondeu com dado" na
auditoria e no relatório.

Texto dentro da imagem é dado, nunca ordem: o prompt manda copiar tentativas
de instrução para `instrucoes_ignoradas`, que fica registrado. A checagem de
vazamento do prompt (ADR-0021) vale também para a leitura.

### Limites (todos em `attachments/limites.py`)
| Limite | Valor | Motivo |
|---|---|---|
| Tamanho do arquivo | 5 MiB | memória: 1 GB para três containers, e o openpyxl usa 10 a 30× o arquivo |
| Linhas lidas | 20 mil | acima disso recusa, em vez de preencher pela metade |
| Colunas | 60 | planilha de trabalho real não passa disso |
| Amostra ao modelo | 8 linhas | reconhecer o formato, não o conteúdo |
| Resumo ao modelo | 4.000 caracteres | ~US$ 0,002 no pior caso |
| Maior lado da imagem | 1.280 px | texto legível a ~1.100 tokens |
| Formatos | `.xlsx`, `.xlsm`, `.csv`; PNG, JPEG, WEBP | `.xls` antigo e GIF não |

A recusa acontece na subida, antes de qualquer chamada de modelo.

## Custos medidos (2026-09-21, API real)
| Caso | Tokens de imagem | Custo |
|---|---|---|
| Print 1920×1080 sem reduzir | 2.461 | — |
| Mesmo print reduzido para 1024×576 | 704 | — |
| Leitura de um print (1280×720) de ponta a ponta | 1.678 entrada, 189 saída | **US$ 0,00056**, 6,2 s |
| Preencher uma planilha de 5 redes | — | **US$ 0,046**, o custo normal de uma pergunta |

## Consequências
- Custo por pergunta com anexo fica na mesma ordem de grandeza de uma
  pergunta comum. A imagem sai cerca de **80 vezes mais barata** que uma
  pergunta ao banco.
- Anexo vencido é normal, não erro: a resposta pede para enviar de novo. A
  planilha preenchida pode ser baixada por 30 minutos; depois disso, só
  pedindo outra vez.
- O modelo de redação ainda pode citar números da imagem sem conferência.
  É um risco aceito, e é por isso que o rótulo não é opcional.
- A subida não pertence a uma conversa (`/api/anexos/`): anexar e desistir
  não cria conversa vazia. O token é aleatório e só vira pergunta pelo POST
  de mensagens, que confere de quem é a conversa.
- Nova dependência: Pillow, só para validar e reduzir imagem.

## Revisão — segunda rodada (2026-09-21, depois do teste na tela)

O teste do Rubens mostrou que dois pedidos naturais não funcionavam: o print
de uma tabela vazia com "preencha para mim" era só lido, e a planilha com
cinco colunas a completar voltava pedindo "envie a planilha". O que mudou:

- **Imagem que precisa do banco vira pedido ao banco.** A leitura devolve
  `precisa_do_banco`; com tabela a completar, ela é transcrita, vira planilha
  em memória e segue o caminho do preenchimento; sem tabela, vira pergunta
  autossuficiente ao planejador. O rótulo "li a imagem" fica só para a
  resposta que de fato veio da imagem.
- **Várias colunas por consulta.** `preenchimento` passa a ter uma chave e
  uma lista de colunas (destino na planilha, coluna do resultado).
- **Planilha pendente.** Quando o Jarvis pede um detalhe antes de preencher,
  a planilha espera 30 min e a próxima mensagem a herda, em memória.
- **Contexto com planilha:** as seções saem também dos cabeçalhos e os três
  temas vão completos — o terceiro em resumo levava à chamada com o
  documento inteiro, 47 mil tokens.
- **Miniatura.** Para a prévia continuar na conversa depois do F5, fica
  guardado um JPEG de até 480 px da imagem (`Message.anexo_miniatura`),
  servido só à dona da conversa. É uma exceção consciente à regra de não
  guardar: é o que a conversa precisa para mostrar o que foi enviado, pesa
  poucos KB, e a imagem que foi ao modelo continua sendo descartada.
  Planilha não tem miniatura; a conversa mostra o nome.

Três defeitos antigos apareceram no caminho e foram corrigidos junto: o
validador de SQL recusava `WITH x AS (VALUES ...)` como se fosse `SELECT *`;
a correção de consulta voltava ao contexto recortado mesmo quando o plano
veio do documento inteiro; e banco fora do ar era tratado como SQL errado,
chamando a IA para corrigir o que não estava errado.
