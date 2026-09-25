"""O gráfico da resposta, desenhado no servidor como PNG (ADR-0028).

No chat web quem desenha é o navegador (Chart.js ou Vega-Lite). No WhatsApp
não há navegador: a imagem sai daqui, pelo `vl-convert` (Vega-Lite → PNG,
sem browser e sem rede), com a mesma especificação e os mesmos dados do
banco. O princípio do ADR-0020 não muda: a IA escreve o desenho, os números
vêm da consulta.

O formato simples (tipo, x, séries, grupo, empilhado, separar) é traduzido
aqui para Vega-Lite. O que o Chart.js da tela faz de ajuste (categoria em
número vira "Categoria 1", corte em 14 barras, mês no eixo) é refeito na
especificação, para o PNG contar a mesma história que a tela.
"""

import copy
import json
import logging
import re

logger = logging.getLogger(__name__)

LARGURA = 560
ALTURA = 300
MAX_CATEGORIAS = 14
MAX_FATIAS = 8
_DATA = re.compile(r"^\d{4}-\d{2}(-\d{2})?")
_PERCENTUAL = re.compile(r"(^|_)(pct|perc|percent|percentual|share|participacao)(?=_|$)", re.I)

TEMA = {
    "font": "Inter, Helvetica, Arial, sans-serif",
    "background": "#FFFFFF",
    "view": {"stroke": None},
    "mark": {"color": "#5558D4"},
    "axis": {"labelColor": "#5E6484", "titleColor": "#5E6484", "gridColor": "#E8E9F2",
             "domain": False, "tickColor": "#E8E9F2", "labelFontSize": 11, "titleFontSize": 11},
    "legend": {"labelColor": "#454A66", "titleColor": "#454A66", "orient": "bottom", "labelFontSize": 11},
    "title": {"color": "#1B1E33", "fontSize": 14, "anchor": "start"},
    "range": {"category": ["#5558D4", "#3FB868", "#F5A623", "#E5484D", "#0EA5E9", "#A855F7",
                           "#14B8A6", "#F472B6"]},
    "header": {"labelFontSize": 12, "labelColor": "#454A66", "title": None},
}


def _rotulo(coluna: str) -> str:
    texto = re.sub(r"_+", " ", _PERCENTUAL.sub("", coluna or "")).strip()
    return texto[:1].upper() + texto[1:]


def _linhas(dados: dict) -> list:
    """Linhas como dicionários, com data ao meio-dia: "2026-01-01" lido como
    UTC virava dezembro no fuso de Brasília (o mesmo tropeço da tela)."""
    colunas = dados.get("columns") or []
    saida = []
    for linha in dados.get("rows") or []:
        registro = {}
        for coluna, valor in zip(colunas, linha):
            if isinstance(valor, str) and _DATA.match(valor) and len(valor) <= 10:
                valor = (valor if len(valor) == 10 else f"{valor}-01") + "T12:00:00"
            registro[coluna] = valor
        saida.append(registro)
    return saida


def _temporal(valores) -> bool:
    presentes = [v for v in valores if v is not None]
    return bool(presentes) and all(isinstance(v, str) and _DATA.match(v) for v in presentes)


def _numero(coluna: str) -> dict:
    return {"format": ",.1f" if _PERCENTUAL.search(coluna or "") else ",.0f"}


def de_simples(grafico: dict, dados: dict) -> dict | None:
    """O formato simples (ADR-0020) em Vega-Lite."""
    colunas = dados.get("columns") or []
    x = grafico.get("x")
    series = [s for s in grafico.get("series") or [] if s in colunas]
    if x not in colunas or not series:
        return None
    tipo = grafico.get("tipo") or "barras"
    grupo = grafico.get("grupo") if grafico.get("grupo") in colunas else ""
    linhas = _linhas(dados)
    temporal = _temporal([r.get(x) for r in linhas])
    transformacoes = []

    avisos = []
    if not temporal and not grupo and tipo != "pizza":
        corte = grafico.get("limite") or MAX_CATEGORIAS
        if len(linhas) > corte:
            # Cortava sem dizer (2026-09-25); a tela avisa "Mostrando 14 de N".
            avisos.append(f"Mostrando {corte} de {len(linhas)}; a lista inteira está na planilha.")
        linhas = linhas[:corte]
    if grafico.get("series_de_fora"):
        avisos.append(f"{min(len(series), 3)} de {min(len(series), 3) + len(grafico['series_de_fora'])} séries; "
                      "as demais estão na planilha.")

    medida, cor = series[0], None
    subtitulo, ordem = "", []
    if grupo:
        linhas, subtitulo, ordem = _maiores_categorias(linhas, x, grupo, medida, separar=bool(grafico.get("separar")))
        numerico = all(isinstance(r.get(grupo), (int, float)) for r in linhas if r.get(grupo) is not None)
        # Nome de coluna vai dentro de uma expressão do Vega: só o que é
        # identificador simples, para nada no nome virar código.
        if numerico and re.fullmatch(r"\w+", grupo):
            # Categoria em número (1, 3) sozinha não diz de quê.
            transformacoes.append({"calculate": f"'{_rotulo(grupo)} ' + datum['{grupo}']", "as": "_grupo"})
            cor = "_grupo"
        else:
            cor = grupo
    elif len(series) > 1:
        transformacoes.append({"fold": series[:3], "as": ["_serie", "_valor"]})
        transformacoes.append({"calculate": "replace(datum._serie, /_+/g, ' ')", "as": "_serie"})
        medida, cor = "_valor", "_serie"

    if tipo == "pizza":
        # A mesma categoria em várias linhas é uma fatia só; e o que passa das
        # 8 maiores vira "Outras", como na tela. Antes o resto era descartado
        # e as proporções da pizza ficavam erradas (2026-09-25).
        totais = {}
        for r in linhas:
            chave = str(r.get(x) if r.get(x) is not None else "Sem categoria")
            totais[chave] = totais.get(chave, 0) + (r.get(medida) or 0)
        ordenadas = sorted(totais.items(), key=lambda par: -par[1])
        fatias = [{x: nome, medida: valor} for nome, valor in ordenadas[:MAX_FATIAS]]
        resto = ordenadas[MAX_FATIAS:]
        if resto:
            fatias.append({x: "Outras", medida: sum(valor for _, valor in resto)})
            avisos.append(f"{len(resto)} {'fatia menor está somada' if len(resto) == 1 else 'fatias menores estão somadas'} em \"Outras\".")
        titulo = grafico.get("titulo") or ""
        return {
            "data": {"values": fatias},
            "mark": {"type": "arc", "innerRadius": 60},
            "encoding": {
                "theta": {"field": medida, "type": "quantitative"},
                "color": {"field": x, "type": "nominal", "title": None, "sort": None},
            },
            "title": {"text": titulo, "subtitle": " ".join(avisos)} if avisos else titulo,
        }

    eixo_x = {"field": x, "type": "temporal" if temporal else "nominal", "title": None}
    if temporal:
        eixo_x.update({"timeUnit": "yearmonth", "axis": {"format": "%b/%y", "labelAngle": 0}})
        if tipo in ("barras", "barras_horizontais"):
            eixo_x["type"] = "ordinal"
    else:
        eixo_x.update({"sort": None, "axis": {"labelLimit": 140}})
    eixo_y = {"field": medida, "type": "quantitative", "title": _rotulo(series[0]) if not cor or grupo else None,
              "axis": _numero(series[0])}
    if not grafico.get("empilhado"):
        eixo_y["stack"] = None

    marca = {"linha": {"type": "line", "point": True, "strokeWidth": 2.5},
             "area": {"type": "area", "opacity": 0.75, "line": True},
             }.get(tipo, {"type": "bar", "cornerRadiusEnd": 3})
    encoding = {"x": eixo_x, "y": eixo_y,
                "tooltip": [{"field": x}, {"field": medida, "format": ",.2f"}]}
    if tipo == "barras_horizontais":
        encoding["x"], encoding["y"] = eixo_y, {**eixo_x, "axis": {"labelLimit": 180}}
    if cor:
        encoding["color"] = {"field": cor, "type": "nominal", "title": None}
        if ordem and cor == grupo:
            # A maior categoria primeiro, na legenda e na pilha; "Outras" por
            # último e em cinza, como na tela — ela é a soma do resto, não
            # uma categoria.
            cores = [CORES[i % len(CORES)] if v != "Outras" else COR_OUTRAS for i, v in enumerate(ordem)]
            encoding["color"]["scale"] = {"domain": ordem, "range": cores}
            encoding["color"]["sort"] = ordem
            encoding["order"] = {"field": "_ordem", "type": "quantitative", "sort": "descending"}
            # JSON dentro da expressão: nome com aspas não vira código.
            transformacoes.append({"calculate": f"indexof({json.dumps(ordem)}, datum[{json.dumps(grupo)}])", "as": "_ordem"})
        if marca["type"] == "bar" and not grafico.get("empilhado") and not grafico.get("separar"):
            encoding["xOffset" if tipo != "barras_horizontais" else "yOffset"] = {"field": cor}

    spec = {"data": {"values": linhas}, "transform": transformacoes, "mark": marca, "encoding": encoding}
    if grafico.get("separar") and cor:
        # Pequenos múltiplos: um gráfico por categoria, mesma escala.
        interno = {k: spec[k] for k in ("mark", "encoding")}
        interno["encoding"] = {k: v for k, v in interno["encoding"].items() if k not in ("color", "xOffset", "yOffset")}
        interno["encoding"].pop("order", None)
        # Até 3 por linha: 9 painéis em duas colunas davam uma imagem longa
        # demais para o celular. A maior categoria no primeiro painel.
        colunas_do_grid = 3 if len(ordem) > 4 else 2
        interno["width"], interno["height"] = LARGURA // colunas_do_grid - 24, 150 if colunas_do_grid == 3 else ALTURA - 80
        faceta = {"field": cor, "type": "nominal", "title": None}
        if ordem and cor == grupo:
            faceta["sort"] = ordem
        spec = {"data": spec["data"], "transform": transformacoes,
                "facet": faceta, "columns": colunas_do_grid,
                "spec": interno, "resolve": {"scale": {"y": "shared"}}}
    subtitulo = " ".join(filter(None, [subtitulo, *avisos]))
    spec["title"] = {"text": grafico.get("titulo") or "", "subtitle": subtitulo} if subtitulo else (grafico.get("titulo") or "")
    return spec


# As mesmas regras da tela (app.js): 6 séries e o resto em "Outras"; separado,
# até 9 painéis. Trinta especialidades em trinta cores não se leem.
MAX_GRUPOS = 6
COR_OUTRAS = "#9CA1B8"
CORES = TEMA["range"]["category"]
MAX_MULTIPLOS = 9


def _maiores_categorias(linhas, x, grupo, medida, separar: bool):
    totais = {}
    for linha in linhas:
        totais[linha.get(grupo)] = totais.get(linha.get(grupo), 0) + (linha.get(medida) or 0)
    limite = MAX_MULTIPLOS if separar else MAX_GRUPOS
    ordem = [v for v, _ in sorted(totais.items(), key=lambda item: -item[1])]
    if len(totais) <= limite:
        return linhas, "", ordem
    maiores = set(ordem[:limite])
    if separar:
        return ([linha for linha in linhas if linha.get(grupo) in maiores],
                f"as {limite} maiores de {len(totais)}; as demais estão na tabela", ordem[:limite])
    somadas = {}
    saida = []
    for linha in linhas:
        if linha.get(grupo) in maiores:
            saida.append(linha)
            continue
        chave = linha.get(x)
        if chave not in somadas:
            somadas[chave] = {x: chave, grupo: "Outras", medida: 0}
            saida.append(somadas[chave])
        somadas[chave][medida] += linha.get(medida) or 0
    return saida, f"as {limite} maiores de {len(totais)}; as demais somadas em Outras", [*ordem[:limite], "Outras"]


def de_vega(grafico: dict, dados: dict) -> dict | None:
    spec = copy.deepcopy(grafico.get("vega") or {})
    if not spec:
        return None
    # A especificação já foi limpa pelo `ai_orchestrator/vega.py` (sem data,
    # url, href). Os dados entram aqui, como na tela.
    spec["data"] = {"values": _linhas(dados)}
    if grafico.get("titulo") and not spec.get("title"):
        spec["title"] = grafico["titulo"]
    return spec


def png(grafico: dict, dados: dict) -> bytes | None:
    """A imagem do gráfico, ou None se não der para desenhar com segurança."""
    if not grafico or not dados or not dados.get("rows"):
        return None
    spec = de_vega(grafico, dados) if grafico.get("tipo") == "vega" else de_simples(grafico, dados)
    if spec is None:
        return None
    if "facet" not in spec:
        spec.setdefault("width", LARGURA)
        spec.setdefault("height", ALTURA)
    spec["config"] = {**TEMA, **(spec.get("config") or {})}
    try:
        import vl_convert as vlc

        return vlc.vegalite_to_png(
            spec, scale=2, allowed_base_urls=[], format_locale="pt-BR", time_format_locale="pt-BR",
        )
    except Exception:  # noqa: BLE001 — sem gráfico é melhor que sem resposta
        logger.warning("Não consegui desenhar o gráfico para o WhatsApp", exc_info=True)
        return None
