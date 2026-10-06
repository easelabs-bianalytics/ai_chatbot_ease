"""Anexos da conversa: planilha para preencher e imagem para ler (ADR-0024).

Três regras governam este pacote, e as três existem para o anexo não virar
uma fatura:

1. **O arquivo fica com a conversa, não para sempre** (ADR-0034, que
   substitui a regra antiga de nunca guardar). O Redis da task é o cache
   rápido; o arquivo enviado e a planilha devolvida vão para um S3 privado e
   criptografado, na pasta da conversa, enquanto ela existir e até dois anos.
   Apagar a conversa apaga os arquivos de verdade. Antes, só o Redis, com
   prazo de duas horas, e todo deploy apagava os anexos de todo mundo.
2. **O conteúdo não vai para o modelo.** Da planilha sobe o perfil
   (cabeçalhos, tipos, preenchimento, chave, fórmulas e poucos exemplos); as
   linhas vão ao BANCO, como a tabela `anexo.<aba>` da consulta (ADR-0031).
   Da imagem sobe a imagem reduzida. As 20 mil linhas de um xlsx virariam 1 a
   2 milhões de tokens, US$ 2 a 4 por pergunta e uma resposta pior.
3. **Número preenchido vem do banco, nunca do modelo.** O modelo diz qual
   coluna do resultado vai para qual coluna da planilha, e por quê; quem
   escreve na célula é o `openpyxl`, e a conferência (`qa.py`) barra a
   entrega se algo mudou fora do pedido. É a ADR-0010 valendo dentro da
   planilha.
"""
