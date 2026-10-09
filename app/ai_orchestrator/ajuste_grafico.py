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

import copy
import json
import re
import unicodedata

# Mensagem de ajuste é curta. "Quantas unidades por linha de produto em
# agosto de 2026?" tem 'linha' no meio e não pode virar troca de gráfico.
MAX_LETRAS = 70
# Cor e rótulo pedem frase mais longa ("Mude a cor do rótulo de dados p/
# verde quando sobe e vermelho quando desce" tem 72): o limite é outro, e
# quem barra assunto novo é `fala_so_do_desenho`.
MAX_LETRAS_DE_COR = 120

# As cores da tela (styles.css): --success, --error e a paleta do gráfico.
VERDE, VERMELHO = "#3FB868", "#E5484D"
_CORES_POR_NOME = {
    "verde": VERDE, "vermelho": VERMELHO, "vermelha": VERMELHO, "azul": "#5558D4",
    "laranja": "#F5A623", "roxo": "#A855F7", "roxa": "#A855F7", "cinza": "#9CA1B8",
    "amarelo": "#F5C518", "amarela": "#F5C518", "preto": "#2B2F45", "preta": "#2B2F45",
}
# "verde quando sobe e vermelho quando desce" (conversa 86, 2026-10-08): a
# cor segue o sinal do número. Antes isso refazia a consulta (US$ 0,03).
_COR_DO_SINAL = re.compile(r"\b(?:verdes?|vermelh[oa]s?)\b")
_SINAL = re.compile(
    r"\b(?:sob\w*|sub\w*|desc\w*|cai\w*|positiv\w*|negativ\w*|cresc\w*|queda|alta|baixa|aument\w*|diminu\w*)\b"
)
_ROTULO = re.compile(r"\b(?:rotulos?|labels?|valores|numeros)\b")
_TIRA_ROTULO = re.compile(r"\b(?:tir\w*|remov\w*|sem|escond\w*|ocult\w*)\b(?:\s+\S+){0,3}?\s+(?:rotulos?|labels?|valores|numeros)\b")
_POE_ROTULO = re.compile(
    r"\b(?:mostr\w*|coloc\w*|adicion\w*|inclu\w*|bot\w*|com|exib\w*|poe|ponha)\b(?:\s+\S+){0,3}?\s+"
    r"(?:rotulos?|labels?|valores|numeros)\b"
)
_COR_FIXA = re.compile(r"\b(?:em|de|para|pra|cor)\s+(" + "|".join(_CORES_POR_NOME) + r")\b")

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


# "Apenas/só/somente ... gráfico" diz que é só o gráfico mesmo com um verbo de
# dado na frase: "Compare apenas enviando um gráfico, os outros canais"
# (conversa 64, 2026-10-02) caía no "compar" e ia sem a instrução de pedido
# visual — o modelo mandou só o gráfico, sem texto, e a resposta virou erro.
_SO_O_VISUAL = re.compile(
    r"\b(?:apenas|so|somente|unicamente)\b(?:\s+\S+){0,3}?\s+(?:um|o|os|uns|em|por|de)?\s*"
    r"(?:graficos?|visual|visualizacao)\b"
)


def pedido_so_visual(mensagem: str) -> bool:
    """A pessoa pediu explicitamente um gráfico, e só ele."""
    texto = _normalizar(mensagem)
    if _SO_O_VISUAL.search(texto) and not re.search(r"\b(?:tabelas?|planilha|excel)\b", texto):
        return True
    return bool(_PEDE_VISUAL.search(texto)) and not _PEDE_DADO.search(texto)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", (texto or "").strip().lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")


def ler_ajuste(mensagem: str) -> dict | None:
    """Lê o pedido de ajuste, ou devolve None se não for um.

    Devolve `{"tipo": ..., "limite": ...}` com as chaves que o usuário pediu:
    quem só trocou o tipo mantém o corte que estava valendo, e vice-versa."""
    texto = _normalizar(mensagem)
    if not texto or len(texto) > MAX_LETRAS_DE_COR:
        return None
    de_cor = _ler_cor_e_rotulo(texto)
    if len(texto) > MAX_LETRAS:
        return de_cor or None

    if _POR_CATEGORIA.search(texto):
        return de_cor or None

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

    ajuste.update(de_cor)
    return ajuste or None


def _ler_cor_e_rotulo(texto: str) -> dict:
    ajuste = {}
    if _COR_DO_SINAL.search(texto) and _SINAL.search(texto):
        ajuste["cores_por_sinal"] = "rotulo" if _ROTULO.search(texto) else "barra"
    else:
        cor = _COR_FIXA.search(texto)
        if cor and re.search(r"\b(?:cor|cores|pint\w*|barras?|linhas?|grafico)\b", texto):
            ajuste["cor"] = _CORES_POR_NOME[cor.group(1)]
    if _TIRA_ROTULO.search(texto):
        ajuste["rotulos"] = False
    elif _POE_ROTULO.search(texto) or ajuste.get("cores_por_sinal") == "rotulo":
        ajuste["rotulos"] = True
    return ajuste


# Ajustes que só pintam ou rotulam: valem também na especificação Vega.
SO_COR_E_ROTULO = frozenset({"cores_por_sinal", "cor", "rotulos"})


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
    if ajuste.get("cores_por_sinal"):
        novo["cores_por_sinal"] = ajuste["cores_por_sinal"]
        novo.pop("cor", None)
    if ajuste.get("cor"):
        novo["cor"] = ajuste["cor"]
        novo.pop("cores_por_sinal", None)
    if "rotulos" in ajuste:
        novo["rotulos"] = ajuste["rotulos"]
    return novo


def aplicar_no_vega(spec: dict, ajuste: dict) -> dict | None:
    """Cor e rótulo numa especificação Vega-Lite, sem o modelo.

    Só a forma simples — uma marca, ou camadas — com uma medida
    quantitativa que se encontre sem dúvida. O resto (facetas, concat) volta
    None e vai para a IA, que conhece os campos."""
    novo = copy.deepcopy(spec or {})
    compostos = {"facet", "concat", "hconcat", "vconcat", "repeat", "spec"}
    if not novo or not ({"mark", "layer"} & novo.keys()) or compostos & novo.keys():
        return None
    if "layer" not in novo:
        novo["layer"] = [{"mark": novo.pop("mark"), "encoding": novo.pop("encoding", {})}]
    comum = novo.get("encoding") or {}
    desenhos = [c for c in novo["layer"] if _marca(c) in ("bar", "line", "area", "point")]
    textos = [c for c in novo["layer"] if _marca(c) == "text"]
    if not desenhos:
        return None
    canais = {**comum, **(desenhos[0].get("encoding") or {})}
    medida, eixo = _medida(canais)
    if not medida:
        return None

    if ajuste.get("rotulos") is False:
        novo["layer"] = [c for c in novo["layer"] if _marca(c) != "text"]
        textos = []
    elif ajuste.get("rotulos") and not textos:
        marca = {"type": "text", "fontWeight": 600, "fontSize": 11}
        marca.update({"align": "left", "dx": 5} if eixo == "x" else {"baseline": "bottom", "dy": -5})
        encoding = {k: v for k, v in canais.items() if k in ("x", "y", "xOffset", "yOffset")}
        encoding["text"] = {"field": medida, "type": "quantitative", "format": ",.2~f"}
        textos = [{"mark": marca, "encoding": encoding}]
        novo["layer"].append(textos[0])

    if ajuste.get("cores_por_sinal"):
        alvos = textos if ajuste["cores_por_sinal"] == "rotulo" else desenhos
        if not alvos:
            return None
        for camada in alvos:
            camada.setdefault("encoding", {})["color"] = {
                "condition": {"test": f"datum[{json.dumps(medida)}] < 0", "value": VERMELHO}, "value": VERDE,
            }
    if ajuste.get("cor"):
        if "field" in (canais.get("color") or {}):
            # Uma cor por série: pintar tudo de uma cor apagaria a legenda.
            return None
        for camada in desenhos:
            marca = camada["mark"] if isinstance(camada["mark"], dict) else {"type": camada["mark"]}
            camada["mark"] = {**marca, "color": ajuste["cor"]}
            (camada.get("encoding") or {}).pop("color", None)
        comum.pop("color", None)
    return novo


def _marca(camada) -> str:
    marca = camada.get("mark")
    return (marca.get("type") if isinstance(marca, dict) else marca) or ""


def _medida(canais: dict) -> tuple:
    for eixo in ("y", "x"):
        canal = canais.get(eixo) or {}
        if canal.get("type") == "quantitative" and canal.get("field"):
            return canal["field"], eixo
    return "", ""


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
    if ajuste.get("cores_por_sinal"):
        o_que = "os valores" if ajuste["cores_por_sinal"] == "rotulo" else "as barras"
        partes.append(f"deixei {o_que} em verde quando sobe e em vermelho quando desce")
    elif ajuste.get("rotulos"):
        partes.append("coloquei os valores no gráfico")
    if ajuste.get("rotulos") is False:
        partes.append("tirei os valores do gráfico")
    if ajuste.get("cor"):
        nome = next((n for n, c in _CORES_POR_NOME.items() if c == ajuste["cor"]), "a cor pedida")
        partes.append(f"pintei o gráfico de {nome}")

    texto = "Pronto: " + " e ".join(partes) + "."
    if ajuste.get("limite") and total and total > ajuste["limite"]:
        texto += f" A tabela acima continua com as {total} linhas."
    return texto


# ------------------------------------------------ só fala do desenho?

# Palavras que um pedido de AJUSTE DE DESENHO usa. "top 5 representantes em
# vendas de agosto", "mostra os 3 maiores CDs em ruptura" e "quero em linha o
# sell out da Raia em 2026" tinham cara de ajuste (corte, tipo) mas traziam
# assunto novo — e redesenhavam o gráfico antigo (2026-10-02). A regra só vale
# quando TODA palavra da mensagem é de desenho, de cortesia, ou já está no
# gráfico da tela (coluna ou categoria).
_PALAVRAS_DO_DESENHO = frozenset("""
    muda mude mudar troca troque trocar coloca coloque colocar passa passe passar deixa deixe deixar
    transforma transforme pode poderia quero queria prefiro faz faca fazer mostra mostre mostrar ver exibe
    exiba volta volte voltar usa use usar separa separe separar separado separada separados separadas
    junta junte juntar juntos juntas empilha empilhe empilhar empilhado empilhada empilhados empilhadas
    ficou fica ficar vira virar desenha desenhe desenhar plota plote plotar
    grafico graficos visual visualizacao desenho barra barras coluna colunas linha linhas horizontal
    horizontais vertical verticais pizza rosca area serie series eixo legenda cor cores escala tipo formato
    top primeiro primeiros primeira primeiras maior maiores menor menores melhor melhores pior piores
    todos todas tudo completo inteiro so somente apenas
    o a os as um uma uns umas de do da dos das em no na nos nas para pra pro com sem e ou ao aos
    isso esse essa este esta nisso nesse nessa ele ela eles elas me mim eu voce vc agora entao tambem
    mesmo mesma lado cada outro outra outros outras forma jeito modo assim aqui ai bom boa ruim nao sim
    ok obrigado obrigada valeu novo novamente favor que mais menos
    rotulo rotulos label labels dado dados valor valores numero numeros p quando sobe subir subiu desce descer
    desceu cai cair caiu positivo positivos negativo negativos positiva negativa crescimento cresce queda alta
    baixa aumenta aumentou diminui diminuiu tira tire tirar remove remova remover esconde esconda adiciona
    adicione inclui inclua bota bote poe ponha pinta pinte pintar ver
    verde verdes vermelho vermelha vermelhos vermelhas azul laranja roxo roxa cinza amarelo amarela preto preta
""".split())
_TOKEN = re.compile(r"[a-z0-9]+")
_CORTE_INTEIRO = re.compile(r"\b(?:top\s*\d{1,3}|\d{1,3}\s*(?:primeir|maior|menor|melhor|pior)\w*)")


def vocabulario_do_grafico(colunas, linhas, colunas_de_categoria) -> set:
    """Palavras que já estão no gráfico: nomes de coluna e as categorias."""
    vocabulario = set()
    for coluna in colunas:
        vocabulario.update(_TOKEN.findall(_normalizar(str(coluna).replace("_", " "))))
    indices = [colunas.index(c) for c in colunas_de_categoria if c in colunas]
    for linha in list(linhas)[:500]:
        for i in indices:
            vocabulario.update(_TOKEN.findall(_normalizar(str(linha[i]))))
    return vocabulario


def _no_vocabulario(palavra: str, vocabulario: set) -> bool:
    if palavra in vocabulario:
        return True
    # "cat" de "categoria", "redes" de "rede": prefixo de 3 letras ou mais.
    return len(palavra) >= 3 and any(
        len(v) >= 3 and (v.startswith(palavra) or palavra.startswith(v)) for v in vocabulario
    )


def fala_so_do_desenho(mensagem: str, vocabulario=frozenset()) -> bool:
    """Toda palavra é de desenho, de cortesia ou já está no gráfico."""
    # O "5" de "top 5" e o "10 maiores" são do corte, inteiros.
    texto = _CORTE_INTEIRO.sub(" ", _normalizar(mensagem))
    for palavra in _TOKEN.findall(texto):
        if palavra in _PALAVRAS_DO_DESENHO or _no_vocabulario(palavra, vocabulario):
            continue
        return False
    return True
