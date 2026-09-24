"""Gráfico em Vega-Lite (ADR-0026): a IA escreve a especificação, o banco dá os dados.

Uma lista de tipos de gráfico nunca acaba — hoje é dispersão, amanhã
cascata, mapa de calor, barras com linha. O Vega-Lite é uma gramática em
JSON que descreve praticamente qualquer gráfico, e o modelo sabe escrevê-la.
O que não muda é o princípio do ADR-0020: **a IA não manda dado nenhum**. Ela
escreve só o desenho (marca, campos, eixos, cores); os valores entram na
tela vindos do resultado da consulta.

Por isso esta validação tira da especificação tudo o que buscaria dado ou
navegaria para fora — `data`, `url`, `href`, a marca `image` — e recusa
campo que não existe no resultado. Um nome de PDV no banco não pode virar
link, script ou requisição na tela de ninguém; as expressões rodam no
interpretador do Vega, que não executa JavaScript.
"""

import json

from ai_orchestrator.grounding import check_grounding

# O desenho de um gráfico cabe folgado nisso; mais que isso é o modelo
# tentando colar dado dentro da especificação.
MAX_CARACTERES = 12000

# Chaves que buscam ou carregam dado de fora, ou abrem link.
_PROIBIDAS = frozenset({"data", "datasets", "url", "href", "usermeta", "$schema", "loader"})
_MARCAS_PROIBIDAS = frozenset({"image"})
# Ao menos uma destas: senão não há desenho.
_RAIZES = frozenset({"mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat", "spec"})
# Onde a especificação cita campo do dado.
_CAMPO = frozenset({"field"})
_LISTAS_DE_CAMPOS = frozenset({"groupby", "fields", "fold", "pivot"})
# Onde uma transformação cria um campo novo (`calculate`, `aggregate`...).
_CRIA_CAMPO = frozenset({"as"})
# Textos que a pessoa lê: número neles precisa de fonte, como no resto.
_TEXTOS = frozenset({"title", "subtitle", "text", "description"})


def _percorrer(no, visitar, chave=None):
    visitar(chave, no)
    if isinstance(no, dict):
        for k, v in no.items():
            _percorrer(v, visitar, k)
    elif isinstance(no, list):
        for v in no:
            _percorrer(v, visitar, chave)


def _limpar(no):
    """Cópia sem as chaves proibidas, em qualquer nível."""
    if isinstance(no, dict):
        return {k: _limpar(v) for k, v in no.items() if k not in _PROIBIDAS}
    if isinstance(no, list):
        return [_limpar(v) for v in no]
    return no


def _campos(spec) -> tuple[set, set]:
    citados, criados = set(), set()

    def visitar(chave, valor):
        if chave in _CAMPO and isinstance(valor, str):
            citados.add(valor)
        elif chave in _LISTAS_DE_CAMPOS and isinstance(valor, list):
            citados.update(v for v in valor if isinstance(v, str))
        elif chave in _CRIA_CAMPO:
            if isinstance(valor, str):
                criados.add(valor)
            elif isinstance(valor, list):
                criados.update(v for v in valor if isinstance(v, str))

    _percorrer(spec, visitar)
    return citados, criados


def _tem_texto_perigoso(spec) -> bool:
    achou = []

    def visitar(chave, valor):
        if isinstance(valor, str) and ("://" in valor or "javascript:" in valor.lower()):
            achou.append(valor)

    _percorrer(spec, visitar)
    return bool(achou)


def _tem_marca_proibida(spec) -> bool:
    achou = []

    def visitar(chave, valor):
        if chave == "mark":
            tipo = valor.get("type") if isinstance(valor, dict) else valor
            if tipo in _MARCAS_PROIBIDAS:
                achou.append(tipo)

    _percorrer(spec, visitar)
    return bool(achou)


def _textos_sem_fonte(spec, columns, rows, question, sql):
    """Apaga título e texto fixo com número que o resultado não sustenta."""
    def limpar(no):
        if isinstance(no, dict):
            novo = {}
            for k, v in no.items():
                if k in _TEXTOS and isinstance(v, str) and not check_grounding(v, columns, rows, question, sql).ok:
                    continue
                novo[k] = limpar(v)
            return novo
        if isinstance(no, list):
            return [limpar(v) for v in no]
        return no

    return limpar(spec)


# ------------------------------------------------ polimento do desenho
#
# Padrões que o modelo escreve e que o Vega desenha mal. Corrigidos aqui, sem
# chamada de modelo, porque são sempre o mesmo erro (conversa 22, 2026-09-24).


def _tipo_da_marca(unidade) -> str:
    marca = unidade.get("mark")
    return marca.get("type", "") if isinstance(marca, dict) else (marca or "")


def _unidades(spec) -> list:
    """A especificação e as camadas dela: onde marcas e eixos moram."""
    camadas = [c for c in spec.get("layer") or () if isinstance(c, dict)]
    return [spec, *camadas]


def _canal(unidade, spec, nome) -> dict:
    """O canal (x, theta, text...) da camada, ou o herdado da especificação."""
    for dono in (unidade, spec):
        canal = (dono.get("encoding") or {}).get(nome)
        if isinstance(canal, dict):
            return canal
    return {}


def _e_mensal(valor) -> bool:
    texto = str(valor or "")
    return len(texto) >= 10 and texto[4] == "-" and texto[8:10] == "01"


def _barras_mensais(spec, columns, rows) -> dict:
    """Barra em eixo de data sai com a largura de um dia, fina como linha; e
    com largura fixa (`size`), a primeira barra invade o eixo Y. Mês a mês é
    categoria ordenada: cada mês ganha a sua faixa, e a linha (de tendência,
    de meta) cai no meio dela."""
    unidades = _unidades(spec)
    campos = {
        _canal(u, spec, "x").get("field")
        for u in unidades
        if _tipo_da_marca(u) == "bar" and _canal(u, spec, "x").get("type") == "temporal"
    } - {None}
    campos = {
        c for c in campos
        if c in columns and rows and all(_e_mensal(linha[columns.index(c)]) for linha in rows)
    }
    if not campos:
        return spec
    for dono in unidades:
        x = (dono.get("encoding") or {}).get("x")
        if isinstance(x, dict) and x.get("field") in campos and x.get("type") == "temporal":
            x["type"] = "ordinal"
            x.setdefault("timeUnit", "yearmonth")
            if isinstance(x.get("axis"), dict) or "axis" not in x:
                eixo = x.setdefault("axis", {})
                if isinstance(eixo, dict):
                    eixo.setdefault("labelAngle", 0)
        marca = dono.get("mark")
        if isinstance(marca, dict) and marca.get("type") == "bar":
            marca.pop("size", None)
            marca.pop("width", None)
    return spec


# A linha sobre as barras, numa cor que se destaca delas nos dois temas.
COR_DA_LINHA_SOBRE_BARRAS = "#F97316"
_TRACEJADA = ("tendencia", "tendência", "projec", "projeç", "previs", "meta")


def _linha_sobre_barras(spec) -> dict:
    """Linha (tendência, projeção, meta) sobre barras, sem cor própria, saía
    da mesma cor das barras e sumia atrás delas. Ganha cor de destaque, e a
    de tendência ou projeção sai tracejada: não é medição."""
    unidades = _unidades(spec)
    if not any(_tipo_da_marca(u) == "bar" for u in unidades):
        return spec
    for unidade in unidades:
        if _tipo_da_marca(unidade) != "line" or "color" in (unidade.get("encoding") or {}):
            continue
        marca = unidade["mark"] if isinstance(unidade.get("mark"), dict) else {"type": "line"}
        unidade["mark"] = marca
        marca.setdefault("color", COR_DA_LINHA_SOBRE_BARRAS)
        if marca.get("point") is True:
            marca["point"] = {"color": marca["color"]}
        elif isinstance(marca.get("point"), dict):
            marca["point"].setdefault("color", marca["color"])
        campo = str(_canal(unidade, spec, "y").get("field") or "").lower()
        if any(p in campo for p in _TRACEJADA):
            marca.setdefault("strokeDash", [6, 4])
    return spec


# Fatia menor que isto não ganha rótulo: o nome dela fica na legenda.
MENOR_FATIA_COM_ROTULO = 0.03


def _rotulos_da_pizza(spec, columns) -> dict:
    """Pizza e rosca com rótulo em cada fatia: as fatias zeradas e as
    pequenas empilhavam os rótulos no topo, ilegíveis. Fatia zerada sai do
    desenho; fatia pequena fica sem rótulo."""
    unidades = _unidades(spec)
    arcos = [u for u in unidades if _tipo_da_marca(u) == "arc"]
    if not arcos:
        return spec
    angulo = _canal(arcos[0], spec, "theta").get("field")
    if angulo not in columns:
        return spec
    filtro = {"filter": f"datum[{json.dumps(angulo)}] > 0"}
    spec["transform"] = [*(spec.get("transform") or []), filtro]
    for unidade in unidades:
        if _tipo_da_marca(unidade) != "text":
            continue
        texto = ((unidade.get("encoding") or {}).get("text") or {})
        campo = texto.get("field") if isinstance(texto, dict) else None
        if not campo or _canal(unidade, spec, "theta").get("field") != angulo:
            continue
        # Sem `stack`, o rótulo cai no começo da fatia, em cima da vizinha. E
        # texto em preto fixo some no tema escuro: a cor fica com o tema.
        for dono in (unidade, *arcos):
            theta = (dono.get("encoding") or {}).get("theta")
            if isinstance(theta, dict):
                theta.setdefault("stack", True)
        (unidade.get("encoding") or {}).pop("color", None)
        unidade["transform"] = [
            *(unidade.get("transform") or []),
            {"joinaggregate": [{"op": "sum", "field": angulo, "as": "__total_das_fatias"}]},
            {"calculate": (
                f"datum[{json.dumps(angulo)}] / datum.__total_das_fatias < {MENOR_FATIA_COM_ROTULO}"
                f" ? '' : datum[{json.dumps(campo)}]"
            ), "as": campo},
        ]
        marca = unidade.get("mark")
        if isinstance(marca, dict):
            marca.setdefault("fontSize", 11)
    return spec


def validar(bruto, columns, rows, question: str, sql: str) -> dict | None:
    """A especificação pronta para a tela, ou None se não der para confiar nela."""
    if isinstance(bruto, str):
        texto = bruto.strip()
        if not texto or len(texto) > MAX_CARACTERES:
            return None
        try:
            spec = json.loads(texto)
        except ValueError:
            return None
    else:
        spec = bruto
    if not isinstance(spec, dict) or not _RAIZES & spec.keys():
        return None
    if _tem_texto_perigoso(spec) or _tem_marca_proibida(spec):
        return None

    spec = _limpar(spec)
    citados, criados = _campos(spec)
    if not citados or citados - set(columns) - criados:
        # Campo que o resultado não tem desenharia um gráfico vazio, ou
        # pior, um gráfico de outra coisa.
        return None
    spec = _textos_sem_fonte(spec, columns, rows, question, sql)
    columns = list(columns)
    spec = _barras_mensais(spec, columns, rows)
    spec = _linha_sobre_barras(spec)
    return _rotulos_da_pizza(spec, columns)
