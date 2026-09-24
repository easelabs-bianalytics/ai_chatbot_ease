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
    ("pizza", r"\bpizza\b|\brosca\b"),
    ("area", r"\barea\b"),
    ("barras", r"\bbarras?\b|\bcolunas?\b"),
    ("linha", r"\blinhas?\b"),
)
_EMPILHAR = re.compile(r"\bempilh")
# "quero ver CAT 1 e CAT 3 de forma separada" (conversa 14, 2026-09-23): um
# gráfico por valor do grupo, lado a lado. "Um gráfico para cada" diz o mesmo.
_SEPARAR = re.compile(
    r"\bseparad[oa]s?\b|\bsepar[ae]\b|\bgraficos?\s+(?:para|pra)\s+cada\b"
    r"|\bgraficos\s+(?:diferentes|distintos|individuais)\b"
)
# "Junto com o sell out" é pedido de dado novo, não de desenho: "junto" e
# "junta com" ficam de fora. E juntar só vale sobre um gráfico já separado
# (conferido no orquestrador).
_JUNTAR = re.compile(r"\bmesmo\s+grafico\b|\bgrafico\s+(?:so|unico)\b|\bjunt(?:a|e|ar)\b(?!\s+(?:com|a|ao|o)\b)")
# "empilhe POR especialidade", "abra POR rede": abrir por uma categoria que
# não está no resultado é dado novo, e quem resolve é a IA com uma consulta.
# Em 2026-09-23 esse pedido não podia ser tratado como troca de desenho.
_POR_CATEGORIA = re.compile(r"\b(?:por|pela|pelo|entre)\s+[a-z]")

# "só os 5 primeiros", "top 10", "os 3 maiores" — o número sempre acompanha
# uma palavra de ranking, senão seria pedido de outro recorte de dado.
_LIMITE = re.compile(r"\b(?:top\s*(\d{1,3})|(\d{1,3})\s*(?:primeir|maior|melhor|pior))")
_TODOS = re.compile(r"\b(?:todos|todas|tudo|completo|inteiro)\b")


# Pedido só visual (conversa 18, 2026-09-24): "Separar as especialidades em
# gráficos (generalista e Neurologia)" voltou com texto, tabela e gráfico, e
# a pessoa só pediu o gráfico. Visual pedido sem nenhum pedido de dado ao
# lado: "qual a evolução de PX em gráfico?" pergunta um dado, e continua com
# a tabela.
_PEDE_VISUAL = re.compile(r"\b(?:graficos?|visual|visualizacao|visao grafica|plot(?:e|ar|a)?|desenh[ae]r?|chart)\b")
_PEDE_DADO = re.compile(
    r"\b(?:tabelas?|listas?|list[ae]r?|numeros?|valores?|planilha|excel|detalh\w*|quant[oa]s?|qua(?:l|is)"
    r"|ranking|total|soma|compar\w*|por que|porque|explique|analise)\b"
)


def pedido_so_visual(mensagem: str) -> bool:
    """A pessoa pediu explicitamente um gráfico, e só ele."""
    texto = _normalizar(mensagem)
    return bool(_PEDE_VISUAL.search(texto)) and not _PEDE_DADO.search(texto)


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

    if _POR_CATEGORIA.search(texto):
        return None

    tem_comando = re.search(_VERBOS, texto) or re.search(_GRAFICO, texto)
    ajuste = {}
    if _EMPILHAR.search(texto):
        ajuste["empilhado"] = True
    if _SEPARAR.search(texto):
        ajuste["separar"] = True
    elif _JUNTAR.search(texto):
        ajuste["separar"] = False

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
    elif tem_comando and _TODOS.search(texto) and "separar" not in ajuste:
        # "junta tudo no mesmo gráfico" fala das séries, não do corte.
        ajuste["limite"] = 0          # 0 = sem corte

    return ajuste or None


def aplicar(grafico: dict, ajuste: dict) -> dict:
    """Devolve a especificação nova do gráfico, preservando o que não mudou."""
    novo = dict(grafico or {})
    if "tipo" in ajuste:
        novo["tipo"] = ajuste["tipo"]
    if ajuste.get("empilhado"):
        novo["empilhado"] = True
        if novo.get("tipo") not in ("barras", "barras_horizontais", "area"):
            novo["tipo"] = "barras"
    if ajuste.get("separar"):
        novo["separar"] = True
        novo.pop("empilhado", None)
        if novo.get("tipo") == "pizza":
            novo["tipo"] = "barras"
    elif ajuste.get("separar") is False:
        novo.pop("separar", None)
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
    "area": "área",
    "pizza": "pizza",
}


def descrever(ajuste: dict, total: int | None = None, grupo: str = "") -> str:
    """O texto que o usuário lê. Curto, e dizendo o que NÃO mudou quando o
    corte pode dar a impressão de que a tabela também encolheu."""
    partes = []
    if "tipo" in ajuste:
        partes.append(f"troquei o gráfico para {NOMES[ajuste['tipo']]}")
    if ajuste.get("empilhado") and not ajuste.get("separar"):
        partes.append("empilhei as séries")
    if ajuste.get("separar"):
        nome = (grupo or "").replace("_", " ").strip()
        partes.append(f"separei em um gráfico por {nome}, na mesma escala" if nome else "separei em gráficos lado a lado")
    elif ajuste.get("separar") is False:
        partes.append("juntei as séries num gráfico só")
    if ajuste.get("limite"):
        n = ajuste["limite"]
        partes.append(f"deixei os {n} primeiros no desenho")
    elif "limite" in ajuste:
        partes.append("voltei a mostrar todos no desenho")

    texto = "Pronto: " + " e ".join(partes) + "."
    if ajuste.get("limite") and total and total > ajuste["limite"]:
        texto += f" A tabela acima continua com as {total} linhas."
    return texto
