"""Limites de anexo, num lugar só.

Todos existem por um motivo de custo ou de memória, e o motivo está ao lado
do número. Mexer aqui é mexer na conta do mês.
"""


class AnexoRecusado(Exception):
    """Anexo fora dos limites. A mensagem é mostrada ao usuário como está,
    então ela diz o que fazer, não o que quebrou."""


# A task do Jarvis tem 1 GB dividido entre três containers, e o openpyxl
# carrega a planilha na memória — tipicamente 10 a 30 vezes o tamanho do
# arquivo. 5 MiB é bem mais que qualquer modelo de planilha de trabalho e
# mantém o pior caso perto de 150 MB.
MAX_BYTES = 5 * 1024 * 1024

# Linhas lidas da planilha. Acima disto o arquivo é recusado em vez de
# truncado: preencher metade de uma planilha sem avisar é pior que recusar.
MAX_LINHAS = 20_000

# Colunas lidas. Planilha de trabalho real não passa disto; um arquivo com
# 2.000 colunas é quase sempre exportação errada.
MAX_COLUNAS = 60

# Linhas de amostra que sobem ao modelo. Oito bastam para ele reconhecer o
# formato de cada coluna (data, texto, número) sem virar volume de token.
LINHAS_DE_AMOSTRA = 8

# Teto do resumo que vai ao modelo, em caracteres (~1.000 tokens, ~US$ 0,002
# na entrada do modelo de planejamento). É o limite que garante que o anexo
# não muda a ordem de grandeza do custo da pergunta.
MAX_CARACTERES_DO_RESUMO = 4_000
# Pasta de trabalho com várias abas ganha mais espaço por aba, até um teto.
# Com 4.000 para oito abas, cada uma chegava ao modelo com ~475 caracteres,
# cortada no meio (Racional Metas 2T26, 2026-10-01). 32.000 caracteres são
# ~8.000 tokens: ~US$ 0,016 no planejador, só em planilha desse tamanho.
CARACTERES_POR_ABA_A_MAIS = 4_000
MAX_CARACTERES_DO_RESUMO_TOTAL = 32_000

# Imagem: medido em 2026-09-21 contra a API, um print de 1920×1080 custa
# 2.461 tokens de entrada; reduzido para 1024 de largura, 704. Até o ADR-0035
# todo print era reduzido a 1.280 px no lado maior.
# Motor dos prints (ADR-0035). Reduzir TODO print para 1.280 px no lado maior
# apagava o texto do print alto ou largo: a lista de 230 CRMs da conversa 44
# virou uma tira ilegível, e a faixa de planilha da conversa 75 também. O que
# manda no custo é a área; o que manda na leitura é o tamanho da letra.
#
# - Área por leitura: o modelo reduz por conta própria o que passa de ~1,5
#   milhão de pixels (o teto de "patches" de 32 px), então cada pedaço fica
#   abaixo disso — ~1.700 tokens, ~US$ 0,0005 no modelo de redação.
# - Lado de cada pedaço: até 2.048 px, o maior que o modelo lê sem reduzir.
# - Print com um lado mais de 2,2 vezes o outro (lista, faixa) não é
#   reduzido para caber: é lido em pedaços, com sobreposição para nenhuma
#   linha cair entre dois, até seis pedaços (~US$ 0,003 no pior caso). O
#   print comum (tela, painel) continua numa leitura só, reduzido pela área.
MAX_PIXELS_POR_LEITURA = 1_450_000
MAX_LADO_POR_LEITURA = 2048
RAZAO_DE_PRINT_LONGO = 2.2
MAX_PEDACOS_DO_PRINT = 6
SOBREPOSICAO_DOS_PEDACOS = 48

FORMATOS_DE_IMAGEM = {"PNG", "JPEG", "WEBP"}
EXTENSOES_DE_PLANILHA = {".xlsx", ".xlsm", ".csv"}

# Prazo dos bytes no depósito. A entrada só precisa sobreviver entre a subida
# e o worker pegar a pergunta; a saída, entre a resposta e o clique em
# baixar. Depois disso, o anexo deixa de existir — de propósito.
SEGUNDOS_DA_ENTRADA = 15 * 60
SEGUNDOS_DA_SAIDA = 30 * 60

# A planilha acompanha a conversa (ADR-0031): a pessoa manda o arquivo e vai
# corrigindo o pedido em várias mensagens ("não ligue pelo painel", "use só
# os CRMs da planilha"). Com 15 minutos, e descartada depois do primeiro
# preenchimento, o Jarvis pedia o arquivo de novo no meio da conversa
# (conversa 44, 2026-09-29). O prazo conta do último uso e é renovado a cada
# mensagem que a usa; continua sendo Redis com prazo, nunca disco nem banco.
SEGUNDOS_DA_PLANILHA_NA_CONVERSA = 2 * 60 * 60
