"""A resposta do Jarvis, montada para o WhatsApp (ADR-0028).

A resposta é a mesma do chat web — mesmo texto, mesmos números, mesma
auditoria. O que muda é a entrega:

- o texto, na marcação do WhatsApp, com as tabelas curtas dentro dele;
- cada gráfico como imagem, desenhada com os dados do banco;
- a lista longa, e a planilha que a pessoa pediu, como arquivo `.xlsx`;
- a planilha preenchida (ADR-0024) de volta, como arquivo;
- as continuações numeradas no fim, para responder com "1", "2" ou "3".
"""

from dataclasses import dataclass, replace

from ai_orchestrator.models import AIReply
from attachments import deposito
from datasource.export import montar_planilha
from messaging import fonte as fonte_da_resposta
from messaging import planilha_da_resposta
from whatsapp import formato, graficos

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Acima disto a tabela não cabe no celular: vai resumida no texto e inteira no arquivo.
LINHAS_NA_CONVERSA = formato.MAX_LINHAS_NA_TABELA
ROTULO_DA_IMAGEM = "_Leitura da imagem — não veio do banco._\n\n"


@dataclass(frozen=True)
class Envio:
    tipo: str                 # "texto" | "imagem" | "documento"
    texto: str = ""           # texto, ou a legenda do arquivo
    dados: bytes = b""
    nome: str = ""
    mimetype: str = ""


def montar(resposta, executor=None) -> list:
    """Os envios de uma resposta (Message de saída), na ordem de leitura."""
    fonte = fonte_da_resposta.montar(resposta) or {}
    textos, imagens, arquivos = [], [], []
    tabela_enviada = False

    if fonte.get("blocos"):
        dados_blocos = fonte.get("dados_blocos") or {}
        for bloco in fonte["blocos"]:
            dados = dados_blocos.get(str(bloco.get("consulta"))) or {}
            if bloco["tipo"] == "texto":
                textos.append(formato.de_markdown(bloco.get("texto", "")))
            elif bloco["tipo"] == "tabela" and dados.get("rows"):
                tabela_enviada = True
                textos.append(_tabela(bloco, dados, arquivos, resposta))
            elif bloco["tipo"] == "grafico":
                _grafico(bloco.get("grafico"), dados, imagens)
    else:
        textos.append(formato.de_markdown(resposta.content))
        _grafico(fonte.get("grafico"), fonte.get("dados") or {}, imagens)

    if fonte.get("decisao") == AIReply.Decision.IMAGE_READING and textos:
        textos[0] = ROTULO_DA_IMAGEM + textos[0]

    consulta = fonte.get("consulta") or {}
    lista_longa = (consulta.get("linhas") or 0) > LINHAS_NA_CONVERSA
    if executor is not None and fonte.get("excel") and not tabela_enviada and (fonte.get("excel_pedido") or lista_longa):
        planilha = planilha_da_resposta.gerar(resposta, resposta.conversation.user, executor)
        if not planilha.erro:
            arquivos.append(Envio("documento", f"{planilha.linhas} linhas", planilha.conteudo, planilha.nome, XLSX))

    pergunta = resposta.in_reply_to
    if pergunta is not None and pergunta.anexo_resposta_token:
        preenchida = deposito.buscar(pergunta.anexo_resposta_token)
        if preenchida:
            nome = pergunta.anexo_resposta_nome or "planilha_preenchida.xlsx"
            arquivos.append(Envio("documento", "Planilha preenchida", preenchida, nome, XLSX))

    sugestoes = fonte.get("sugestoes") or []
    if sugestoes:
        textos.append("*Para continuar, responda com o número:*\n"
                      + "\n".join(f"{i}. {s}" for i, s in enumerate(sugestoes, 1)))

    texto = "\n\n".join(t for t in textos if t).strip()
    envios = [Envio("texto", parte) for parte in formato.dividir(texto)]
    return envios + imagens + arquivos


def _tabela(bloco, dados, arquivos, resposta) -> str:
    colunas = [c for c in (bloco.get("colunas") or dados["columns"]) if c in dados["columns"]]
    indices = [dados["columns"].index(c) for c in colunas]
    linhas = [[linha[i] for i in indices] for linha in dados["rows"]]
    titulo = f"*{bloco['titulo']}*\n" if bloco.get("titulo") else ""
    if len(linhas) <= LINHAS_NA_CONVERSA:
        return titulo + formato.tabela(colunas, linhas)
    conteudo = montar_planilha(colunas, linhas, {
        "pergunta": resposta.in_reply_to.content if resposta.in_reply_to else "",
        "linhas": len(linhas),
        "observacao": "Tabela da resposta do Jarvis no WhatsApp.",
    })
    nome = f"jarvis_tabela_{len(arquivos) + 1}.xlsx"
    arquivos.append(Envio("documento", bloco.get("titulo") or f"{len(linhas)} linhas", conteudo, nome, XLSX))
    return (titulo + formato.tabela(colunas, linhas[:5])
            + f"\n_…e mais {len(linhas) - 5} linhas na planilha {nome}._")


def _grafico(grafico, dados, imagens) -> None:
    imagem = graficos.png(grafico, dados)
    if imagem:
        imagens.append(Envio("imagem", (grafico or {}).get("titulo") or "", imagem, "grafico.png", "image/png"))


