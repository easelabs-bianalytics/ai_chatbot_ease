# ADR-0034: Os arquivos ficam com a conversa, no S3, por até dois anos

## Status
Aceito — 2026-10-06. Substitui a regra 1 de `attachments/__init__.py` ("o
arquivo nunca é armazenado") do ADR-0024 e o prazo de duas horas da planilha
na conversa do ADR-0031.

## Contexto
O anexo (planilha ou print) e a planilha que o Jarvis devolve viviam só no
Redis da própria task, por até duas horas, renovadas a cada uso. Foi uma
escolha de privacidade: as planilhas trazem CRM de médico e, às vezes, CPF de
paciente.

O problema maior era outro. O Redis roda dentro da task do Jarvis, então
todo deploy apagava, na hora, os anexos de todo mundo. Em 2026-10-05 subiram
umas cinco versões, e quem trabalhava com uma planilha perdeu três coisas:

- o "Baixar Excel" das respostas que leram a planilha, que passava a dizer
  "a planilha desta conversa expirou";
- a continuação da conversa sobre o arquivo, que exigia enviar de novo;
- a chance de reproduzir ou auditar uma resposta antiga baseada no arquivo.

Pedido do Rubens: o arquivo fica na conversa; a pessoa sempre pode baixar de
novo o que mandou e o que o Jarvis devolveu. Apagar a conversa apaga o
arquivo, e há um prazo de dois anos.

## Decisão
- **Armazém:** bucket S3 privado `cockpit-prod-jarvis-arquivos-<conta>`
  (Terraform no `sales_force_crm`, `jarvis_arquivos.tf`):
  - criptografado (AES256), com acesso público bloqueado e só HTTPS;
  - sem versionamento: apagar tem de apagar de verdade;
  - só a task do Jarvis lê e grava, e só em `conversas/`.
- **Onde fica cada arquivo:** em `conversas/<id da conversa>/<token>`, com um
  registro `ArquivoDaConversa` (conversa, mensagem, papel entrada ou saída,
  nome, tamanho). O token é o mesmo do depósito, então todo o código que já
  achava o arquivo pelo token continua igual.
- **O Redis vira cache.** `deposito.fixar` guarda no S3 o arquivo que entrou
  na conversa e a planilha devolvida. `deposito.buscar` procura no Redis e,
  quando ele esqueceu (prazo ou deploy), no S3, e devolve ao Redis para o
  próximo uso. Falha do S3 nunca impede a pergunta: ela segue só com o Redis.
- **Prazo:** a regra de ciclo de vida do bucket apaga cada arquivo aos 730
  dias. Depois disso, o download responde "não está mais disponível".
- **Apagar a conversa** (exclusão lógica, ADR-0018) apaga os arquivos dela
  de verdade: no S3, no Redis e o registro.
- **Download:**
  - o arquivo enviado sai em `.../messages/<id>/anexo/`, e a ficha do anexo
    na conversa vira link;
  - a planilha devolvida continua em `.../planilha/`;
  - só a dona da conversa baixa; para qualquer outra pessoa, 404.
- **Sem bucket:** memória só em desenvolvimento e testes. Em produção, o
  armazém fica desligado e nada é registrado, para nenhum registro apontar
  para um arquivo que só um processo vê.

## Consequências
- **Deploy não apaga mais nada:** o arquivo volta do S3 no primeiro uso
  depois do deploy.
- **Custo:** desprezível. O arquivo tem no máximo 5 MB; a 50 por dia, com
  ~1 MB em média, são ~18 GB por ano e ~36 GB no teto de dois anos — menos
  de US$ 2 por mês no S3 Standard de sa-east-1, mais centavos de
  requisições.
- **Dado pessoal guardado por mais tempo.** Antes, ninguém guardava a
  planilha; agora ela fica até dois anos com a conversa. Isso fica
  registrado em `open-decisions.md` (O-08, retenção). A exclusão da conversa
  é o caminho para apagar antes.
- **Ordem do deploy:** o bucket e a permissão vêm antes ou junto da imagem
  que os usa. A migração `messaging.0008` cria a tabela.
