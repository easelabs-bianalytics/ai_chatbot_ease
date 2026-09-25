"""A resposta do Jarvis, montada para o WhatsApp (ADR-0028).

A resposta é a mesma do chat web — mesmo texto, mesmos números, mesma
auditoria. O que muda é a entrega:

- o texto, na marcação do WhatsApp, com as tabelas curtas dentro dele;
- cada gráfico como imagem, desenhada com os dados do banco;
- a lista longa, e a planilha que a pessoa pediu, como arquivo `.xlsx`;
- a planilha preenchida (ADR-0024) de volta, como arquivo;
- as continuações numeradas no fim, para responder com "1", "2" ou "3".
"""

import logging
import re
from dataclasses import dataclass, replace

from ai_orchestrator.models import AIReply
from attachments import deposito
from datasource.export import montar_planilha
from messaging import fonte as fonte_da_resposta
from messaging import planilha_da_resposta
from whatsapp import formato, graficos

logger = logging.getLogger(__name__)

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
                textos.append(_tabela(bloco, dados, arquivos, resposta, executor=executor))
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
            arquivos.append(Envio("documento", _legenda(planilha.linhas, planilha.cortada),
                                  planilha.conteudo, planilha.nome, XLSX))
        else:
            logger.warning("WhatsApp: planilha da resposta não saiu: %s", planilha.erro)

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

    texto = _sem_o_botao_da_tela("\n\n".join(t for t in textos if t).strip(),
                                 tem_planilha=any(a.tipo == "documento" for a in arquivos))
    envios = [Envio("texto", parte) for parte in formato.dividir(texto)]
    return envios + imagens + arquivos


# "Pelo botão "Baixar Excel" logo abaixo desta resposta" é o chat web. No
# WhatsApp a planilha vai anexada (produção, 2026-09-25).
_BOTAO_DA_TELA = re.compile(
    r"(?:pelo|no|o)\s+bot[aã]o\s*[\"“”']?\s*Baixar\s+Excel\s*[\"“”']?(?:\s+logo)?(?:\s+abaixo(?:\s+(?:desta|da)\s+resposta)?)?",
    re.I,
)


def _sem_o_botao_da_tela(texto: str, tem_planilha: bool = True) -> str:
    """Troca o botão da tela pela planilha anexada — só quando ela foi mesmo
    anexada. Se a planilha falhou, o texto não pode prometer um arquivo que
    não vai (2026-09-25)."""
    if tem_planilha:
        return _BOTAO_DA_TELA.sub("na planilha anexada", texto)
    if not _BOTAO_DA_TELA.search(texto):
        return texto
    return (_BOTAO_DA_TELA.sub("na planilha", texto)
            + "\n\n_Não consegui gerar a planilha agora. Peça de novo em instantes._")


def _legenda(linhas: int, cortada: bool = False) -> str:
    texto = f"{linhas:,} linhas".replace(",", ".")
    return texto + " (a lista passou do limite da planilha; filtre para ter o resto)" if cortada else texto


def _tabela(bloco, dados, arquivos, resposta, executor=None) -> str:
    """Tabela curta no texto; longa, em planilha com as primeiras no texto.

    A resposta guarda para a tela só as 100 primeiras linhas (a lista inteira
    é o botão "Baixar Excel"). Em 2026-09-25 "os 10 maiores prescritores de
    cada território" deu 340 linhas e a planilha do WhatsApp saiu com 100 —
    faltava território. Quando a tabela tem mais linhas do que as guardadas,
    a planilha refaz a consulta inteira, como o botão faz."""
    colunas = [c for c in (bloco.get("colunas") or dados["columns"]) if c in dados["columns"]]
    indices = [dados["columns"].index(c) for c in colunas]
    linhas = [[linha[i] for i in indices] for linha in dados["rows"]]
    titulo = f"*{bloco['titulo']}*\n" if bloco.get("titulo") else ""
    total = max(int(dados.get("total") or 0), len(linhas))
    if total <= LINHAS_NA_CONVERSA and not dados.get("truncado"):
        return titulo + formato.tabela(colunas, linhas)
    nome = f"jarvis_tabela_{len(arquivos) + 1}.xlsx"
    inteira = None
    if (total > len(linhas) or dados.get("truncado")) and executor is not None:
        # A consulta DESTA tabela, pelo índice dela — não a última que rodou,
        # que numa resposta com várias consultas é de outra tabela.
        inteira = planilha_da_resposta.gerar(resposta, resposta.conversation.user, executor,
                                             consulta=bloco.get("consulta"))
        if inteira.erro:
            logger.warning("WhatsApp: não consegui refazer a consulta para a planilha: %s", inteira.erro)
            inteira = None
    if inteira is not None:
        conteudo, total_do_arquivo = inteira.conteudo, inteira.linhas
        legenda = bloco.get("titulo") or _legenda(total_do_arquivo, inteira.cortada)
        rodape = f"\n_…e mais {total_do_arquivo - 5:,} linhas na planilha {nome}._".replace(",", ".")
    else:
        # Sem a lista inteira, a legenda e o texto dizem o total real: "100
        # de 340", nunca "100 linhas" como se fosse tudo (2026-09-25).
        conteudo = montar_planilha(colunas, linhas, {
            "pergunta": resposta.in_reply_to.content if resposta.in_reply_to else "",
            "linhas": len(linhas),
            "observacao": f"Tabela da resposta do Jarvis no WhatsApp: as primeiras {len(linhas)} de {total} linhas.",
        })
        parcial = total > len(linhas) or dados.get("truncado")
        legenda = bloco.get("titulo") or (f"{len(linhas)} de {total} linhas" if parcial else f"{len(linhas)} linhas")
        rodape = (f"\n_…a planilha {nome} traz as primeiras {len(linhas)} de {total} linhas; "
                  "não consegui buscar a lista inteira agora. Peça de novo em instantes._"
                  if parcial else f"\n_…e mais {len(linhas) - 5} linhas na planilha {nome}._")
    arquivos.append(Envio("documento", legenda, conteudo, nome, XLSX))
    return titulo + formato.tabela(colunas, linhas[:5]) + rodape


def _grafico(grafico, dados, imagens) -> None:
    imagem = graficos.png(grafico, dados)
    if imagem:
        imagens.append(Envio("imagem", (grafico or {}).get("titulo") or "", imagem, "grafico.png", "image/png"))


