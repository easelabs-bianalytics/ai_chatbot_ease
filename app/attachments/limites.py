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

# Maior lado da imagem depois de reduzida. Medido em 2026-09-21 contra a API:
# um print de 1920×1080 custa 2.461 tokens de entrada; reduzido para 1024 de
# largura, 704. Em 1280 o texto de um print continua legível e o custo fica
# em torno de 1.100 tokens — no modelo de redação, ~US$ 0,0002.
MAX_LADO_DA_IMAGEM = 1280

FORMATOS_DE_IMAGEM = {"PNG", "JPEG", "WEBP"}
EXTENSOES_DE_PLANILHA = {".xlsx", ".xlsm", ".csv"}

# Prazo dos bytes no depósito. A entrada só precisa sobreviver entre a subida
# e o worker pegar a pergunta; a saída, entre a resposta e o clique em
# baixar. Depois disso, o anexo deixa de existir — de propósito.
SEGUNDOS_DA_ENTRADA = 15 * 60
SEGUNDOS_DA_SAIDA = 30 * 60
