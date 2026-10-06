# Arquivos da conversa: onde ficam e como acessar

As planilhas e imagens que as pessoas mandam ao Jarvis, e as planilhas que o
Jarvis devolve preenchidas, ficam guardadas com a conversa. Este documento
explica onde elas ficam, por quanto tempo, quem pode acessar e como. A
decisão e o porquê estão no
[ADR-0034](adr/0034-arquivos-da-conversa-no-s3.md).

**Situação em 2026-10-06:** o código e a infra estão prontos, mas **ainda não
estão em produção**. Até o deploy, os arquivos continuam como antes: só no
Redis da task, por até 2 horas, e cada deploy os apaga. Os pré-requisitos
estão na Fase 9 do [`plan.md`](plan.md).

---

## 1. O que é guardado

| Arquivo | Quando entra | Papel no registro |
|---|---|---|
| Planilha (`.xlsx`, `.xlsm`, `.csv`) enviada na pergunta | no envio | **Enviado pela pessoa** |
| Imagem (print) enviada na pergunta | no envio | **Enviado pela pessoa** |
| Tabela de um print que o Jarvis transformou em planilha | quando ele lê o print | **Enviado pela pessoa** |
| Planilha que o Jarvis devolve preenchida ou alterada | quando a resposta sai | **Devolvido pelo Jarvis** |

Vale para o chat web e para o WhatsApp.

O que **não** é guardado como arquivo: o "Baixar Excel" das respostas. Ele é
gerado na hora, rodando de novo a consulta da resposta; se ela leu a planilha
enviada, usa o arquivo guardado.

## 2. Onde ficam

Num bucket S3 **privado**, na conta AWS da Ease Labs (595324409476), região
São Paulo (`sa-east-1`):

```
s3://cockpit-prod-jarvis-arquivos-595324409476/conversas/<id da conversa>/<token>
```

- uma pasta por conversa (`conversas/45/`, `conversas/46/`…);
- dentro dela, cada arquivo se chama pelo **token**, um código aleatório de
  32 letras, sem extensão. O nome original (`redes_setembro.xlsx`) fica no
  banco do Jarvis, no registro "Arquivo da conversa".

Proteções do bucket:

| Proteção | Como |
|---|---|
| Criptografado | AES256 no S3 |
| Fechado para a internet | acesso público bloqueado nas quatro opções |
| Só por HTTPS | a política do bucket recusa qualquer acesso sem TLS |
| Apagar apaga de verdade | sem versionamento: não sobra cópia antiga |
| O Jarvis só mexe na pasta dele | a permissão da task cobre só `conversas/` |

O Redis da task continua sendo usado, como **cache**: o arquivo usado agora
há pouco vem dele, mais rápido. Quando o Redis esquece (2 horas sem uso, ou
um deploy), o Jarvis busca de volta no S3 sem a pessoa perceber.

Onde está declarado: `sales_force_crm/infra/modules/compute/jarvis_arquivos.tf`.

## 3. Por quanto tempo

- **Até 2 anos** depois do envio. Uma regra do próprio S3 apaga cada arquivo
  aos 730 dias. Depois disso, o download responde *"este arquivo não está
  mais disponível"*.
- **Apagar a conversa apaga os arquivos dela na hora**: no S3, no Redis e o
  registro. A conversa em si some só da lista da pessoa (exclusão lógica,
  ADR-0018), mas os arquivos saem de verdade, porque trazem dado pessoal.

## 4. Quem pode acessar, e como

### 4.1 Pelo chat: a dona ou o dono da conversa
Na própria conversa:
- a **ficha do anexo** na pergunta é um link: clicar baixa o arquivo que foi
  enviado;
- o botão **"Baixar planilha preenchida"** baixa o que o Jarvis devolveu.

Ninguém baixa pelo chat o arquivo da conversa de outra pessoa, nem
administrador: o endereço responde 404.

### 4.2 Pelo Admin do Jarvis: a equipe com permissão
Em `https://jarvis.easelabs.app.br/admin/` → **Mensagens** → **Arquivos da
conversa**:

- a lista mostra, para cada arquivo: conversa, se foi enviado ou devolvido,
  nome original, tamanho, data e o link **Baixar**;
- abrindo um arquivo, aparecem também a mensagem, o token e o caminho no S3;
- **Baixar** devolve o arquivo **com o nome e o tipo originais**
  (`redes_setembro.xlsx`), buscando no Redis ou no S3;
- se o arquivo já foi apagado (prazo de 2 anos ou conversa excluída), aparece
  o aviso *"O arquivo … não está mais disponível"*;
- dá para buscar pelo nome do arquivo, pelo token ou pelo título da conversa,
  e filtrar por papel e por data.

Quem pode baixar: quem entra no Admin **e** tem a permissão de ver "arquivos
da conversa" (todo superusuário tem). Quem é da equipe sem essa permissão
recebe "acesso negado"; quem não é da equipe vai para o login.

Cada download pelo Admin fica no log da aplicação, com quem baixou, qual
arquivo e de qual conversa. Está no CloudWatch, grupo `/aws/ecs/cockpit-prod`,
stream do `jarvis-web`, procurando por `Admin:`:

```
Admin: rubens.filho@easelabs.com.br baixou o arquivo 128 (redes_setembro.xlsx) da conversa 45
```

O Admin **não** cria nem apaga arquivos. Para apagar, apague a conversa.

### 4.3 Pela AWS: console ou linha de comando
Quem tem permissão de administrador na conta AWS (hoje, o usuário `rubens`)
enxerga o bucket inteiro.

- **Console:** S3 → `cockpit-prod-jarvis-arquivos-595324409476` →
  `conversas/` → a pasta da conversa → o arquivo → **Download**.
- **Linha de comando:**

  ```bash
  # arquivos de uma conversa
  aws s3 ls s3://cockpit-prod-jarvis-arquivos-595324409476/conversas/45/

  # baixar um (o nome original está no Admin; o S3 só tem o token)
  aws s3 cp s3://cockpit-prod-jarvis-arquivos-595324409476/conversas/45/<token> redes_setembro.xlsx
  ```

No S3 o arquivo não tem nome nem extensão: é preciso saber pelo Admin qual
token é qual arquivo, e dar o nome ao salvar. **Para o dia a dia, prefira o
Admin**: ele já devolve o nome certo e deixa o download registrado. A AWS
**não** registra, por padrão, quem leu um arquivo do bucket (ver a seção 7).

## 5. Quanto custa

Desprezível. Cada arquivo tem no máximo 5 MB. Com uns 50 arquivos por dia de
~1 MB, são ~18 GB por ano e ~36 GB no teto de 2 anos: **menos de US$ 2 por
mês** no S3 Standard de São Paulo, mais centavos de requisições.

## 6. Perguntas frequentes

**Fiz um deploy. Os arquivos somem?**
Não, depois que esta versão estiver no ar. O Redis é zerado, mas o arquivo
volta do S3 no primeiro uso.

**A pessoa apagou a conversa por engano. Dá para recuperar o arquivo?**
Não. Apagar a conversa apaga os arquivos de verdade, sem cópia: é a garantia
de que dado pessoal não fica guardado depois que a pessoa pede para apagar.

**O S3 caiu. O Jarvis para?**
Não. Guardar no S3 é uma garantia a mais, nunca uma condição: a pergunta
segue com o arquivo no Redis, como era antes, e a falha fica no log.

**E se a imagem do Jarvis subir antes do bucket existir?**
O Jarvis funciona como antes (só Redis) e avisa no log que o bucket não está
configurado. Nada é registrado como guardado sem estar.

**O modelo de IA vê o arquivo?**
Não muda nada aqui: o modelo continua recebendo só o resumo da planilha
(cabeçalhos, tipos, alguns exemplos), e as linhas vão para o banco da
consulta (ADR-0031). Guardar o arquivo não manda nada a mais para a IA.

## 7. Cuidados

- **Dado pessoal guardado por mais tempo.** Antes, ninguém guardava a
  planilha; agora ela fica até 2 anos. A retenção está registrada em
  `open-decisions.md` (O-08).
- **Quem leu pela AWS não fica registrado.** O download pelo Admin vai para o
  log; o acesso direto pelo console ou pela linha de comando, não. Para
  registrar também esse caminho, dá para ligar os eventos de dados do S3 no
  CloudTrail só para este bucket (alguns dólares por mês). Ainda não está
  ligado.
- **Permissão no Admin.** Ao dar acesso ao Admin a alguém, só inclua a
  permissão "pode ver arquivo da conversa" se a pessoa precisar baixar
  planilhas dos outros.

## 8. Onde está cada peça

| Peça | Arquivo |
|---|---|
| Decisão | `docs/adr/0034-arquivos-da-conversa-no-s3.md` |
| Guardar, buscar e apagar (Redis + S3) | `app/attachments/deposito.py` |
| Conexão com o S3 (e o armazém de memória dos testes) | `app/attachments/armazem.py` |
| Registro de cada arquivo | `ArquivoDaConversa` em `app/messaging/models.py` (migração `0008`) |
| Download pelo chat | `MessageAnexoView` e `MessagePlanilhaView` em `app/messaging/views.py` |
| Download pelo Admin | `ArquivoDaConversaAdmin` em `app/messaging/admin.py` |
| Apagar ao excluir a conversa | `ConversationDetailView.delete` em `app/messaging/views.py` |
| Bucket, regras e permissão | `sales_force_crm/infra/modules/compute/jarvis_arquivos.tf` |
| Variável `JARVIS_ARQUIVOS_BUCKET` | `sales_force_crm/infra/modules/compute/jarvis.tf` |
| Testes | `tests/integration/test_arquivos_da_conversa.py` |
