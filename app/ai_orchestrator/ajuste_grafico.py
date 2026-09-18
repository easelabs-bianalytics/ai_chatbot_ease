"""Ajuste do gráfico pela conversa, sem consultar o banco nem o modelo.

Depois de ver o resultado, o pedido seguinte costuma ser sobre o desenho e
não sobre o dado: *"muda para barras"*, *"só os cinco primeiros"*. Os números
já estão na tela — refazer a consulta e pagar duas chamadas de modelo para
trocar um tipo de gráfico seria desperdício, e ainda arriscaria voltar um
número diferente do que a pessoa está olhando.

Por isso isto é regra, não IA. A regra só dispara quando a conversa tem um
gráfico à vista e a mensagem é curta e inequívoca: pergunta de dado nunca
pode ser confundida com ajuste de desenho.
"""

import re
import unicodedata

# Mensagem de ajuste é curta. "Quantas unidades por linha de produto em
# agosto de 2026?" tem 'linha' no meio e não pode virar troca de gráfico.
MAX_LETRAS = 70

_VERBOS = r"(?:mud[ae]|muda|troc[ae]|troque|coloc[ae]|pass[ae]|deix[ae]|transform[ae]|pod[ei]|quero|prefiro|faz|faca)"
_GRAFICO = r"(?:grafico|visual|desenho)"

_TIPOS = (
    ("barras_horizontais", r"barras?\s+horizontais?|horizontal"),
    ("barras", r"\bbarras?\b|\bcolunas?\b"),
    ("linha", r"\blinhas?\b"),
)

# "só os 5 primeiros", "top 10", "os 3 maiores" — o número sempre acompanha
# uma palavra de ranking, senão seria pedido de outro recorte de dado.
_LIMITE = re.compile(r"\b(?:top\s*(\d{1,3})|(\d{1,3})\s*(?:primeir|maior|melhor|pior))")
_TODOS = re.compile(r"\b(?:todos|todas|tudo|completo|inteiro)\b")


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", (texto or "").strip().lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")


def ler_ajuste(mensagem: str) -> dict | None:
    """Lê o pedido de ajuste, ou devolve None se não for um.

    Devolve `{"tipo": ..., "limite": ...}` com as chaves que o usuário pediu:
    quem só trocou o tipo mantém o corte que estava valendo, e vice-versa."""
    texto = _normalizar(mensagem)
    if not texto or len(texto) > MAX_LETRAS:
        return None

    tem_comando = re.search(_VERBOS, texto) or re.search(_GRAFICO, texto)
    ajuste = {}

    if tem_comando:
        for nome, padrao in _TIPOS:
            if re.search(padrao, texto):
                ajuste["tipo"] = nome
                break

    limite = _LIMITE.search(texto)
    if limite:
        valor = int(limite.group(1) or limite.group(2))
        if valor > 0:
            ajuste["limite"] = valor
    elif tem_comando and _TODOS.search(texto):
        ajuste["limite"] = 0          # 0 = sem corte

    return ajuste or None


def aplicar(grafico: dict, ajuste: dict) -> dict:
    """Devolve a especificação nova do gráfico, preservando o que não mudou."""
    novo = dict(grafico or {})
    if "tipo" in ajuste:
        novo["tipo"] = ajuste["tipo"]
    if "limite" in ajuste:
        if ajuste["limite"]:
            novo["limite"] = ajuste["limite"]
        else:
            novo.pop("limite", None)
    return novo


NOMES = {
    "linha": "linha",
    "barras": "barras",
    "barras_horizontais": "barras horizontais",
}


def descrever(ajuste: dict, total: int | None = None) -> str:
    """O texto que o usuário lê. Curto, e dizendo o que NÃO mudou quando o
    corte pode dar a impressão de que a tabela também encolheu."""
    partes = []
    if "tipo" in ajuste:
        partes.append(f"troquei o gráfico para {NOMES[ajuste['tipo']]}")
    if ajuste.get("limite"):
        n = ajuste["limite"]
        partes.append(f"deixei os {n} primeiros no desenho")
    elif "limite" in ajuste:
        partes.append("voltei a mostrar todos no desenho")

    texto = "Pronto: " + " e ".join(partes) + "."
    if ajuste.get("limite") and total and total > ajuste["limite"]:
        texto += f" A tabela acima continua com as {total} linhas."
    return texto
