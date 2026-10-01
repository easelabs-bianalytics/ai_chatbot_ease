"""Anexos da conversa: planilha para preencher e imagem para ler (ADR-0024).

Três regras governam este pacote, e as três existem para o anexo não virar
uma fatura:

1. **O arquivo nunca é armazenado.** Os bytes ficam no Redis da própria task,
   com prazo: a imagem até a resposta sair, a planilha duas horas depois do
   último uso (ela acompanha a conversa, ADR-0031). A conversa guarda o nome
   e o resumo em texto — o suficiente para a pessoa (e para a auditoria)
   saber o que foi enviado.
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
