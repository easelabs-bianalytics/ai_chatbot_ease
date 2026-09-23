"""Anexo recebido: valida, resume e guarda no depósito (ADR-0024).

Um lugar só para as duas portas de entrada — o botão de anexar do chat web e
o documento ou a imagem mandados no WhatsApp (ADR-0028). O arquivo não é
salvo: os bytes vão para o depósito com prazo, e o que volta é a etiqueta
(token, tipo, nome, resumo).
"""

from pathlib import Path

from attachments import deposito
from attachments.imagem import preparar as preparar_imagem
from attachments.limites import EXTENSOES_DE_PLANILHA, MAX_BYTES, AnexoRecusado
from attachments.planilha import ler_estrutura


def preparar_anexo(nome: str, dados: bytes) -> dict:
    """A etiqueta do anexo, já no depósito. Levanta `AnexoRecusado` com a
    frase que a pessoa lê."""
    if len(dados) > MAX_BYTES:
        raise AnexoRecusado(f"O arquivo tem mais de {MAX_BYTES // (1024 * 1024)} MB. Envie um recorte menor.")
    nome = (nome or "arquivo")[:255]
    if Path(nome).suffix.lower() in EXTENSOES_DE_PLANILHA:
        estrutura = ler_estrutura(nome, dados)
        resumo = estrutura.resumo
        tipo = "planilha"
        detalhe = {"linhas": estrutura.linhas, "colunas": [c.nome for c in estrutura.colunas]}
    else:
        preparada = preparar_imagem(dados)
        # Guarda a imagem REDUZIDA, não a original: é ela que vai ao modelo,
        # e o original não serve para mais nada.
        dados = preparada.dados
        resumo = (
            f"Imagem {preparada.formato_original} de {preparada.largura}×{preparada.altura}"
            + (" (reduzida)" if preparada.reduzida else "")
        )
        tipo = "imagem"
        detalhe = {
            "largura": preparada.largura,
            "altura": preparada.altura,
            "tokens_estimados": preparada.tokens_estimados,
        }
    return {"token": deposito.guardar(dados), "tipo": tipo, "nome": nome, "resumo": resumo, "detalhe": detalhe}
