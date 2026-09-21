"""Anexos da conversa: planilha para preencher e imagem para ler (ADR-0024).

Três regras governam este pacote, e as três existem para o anexo não virar
uma fatura:

1. **O arquivo nunca é armazenado.** Os bytes ficam no Redis da própria task,
   com prazo curto, e são descartados assim que a resposta sai. A conversa
   guarda o nome e o resumo em texto — o suficiente para a pessoa (e para a
   auditoria) saber o que foi enviado.
2. **O conteúdo não vai para o modelo.** Da planilha sobem cabeçalhos, tipos
   e um punhado de linhas de amostra; da imagem sobe a imagem reduzida. As 20
   mil linhas de um xlsx virariam 1 a 2 milhões de tokens, US$ 2 a 4 por
   pergunta e uma resposta pior.
3. **Número preenchido vem do banco, nunca do modelo.** O modelo diz qual
   coluna casa com qual; quem escreve na célula é o `openpyxl` com o
   resultado da consulta. É a ADR-0010 valendo dentro da planilha.
"""
