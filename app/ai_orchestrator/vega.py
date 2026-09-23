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
    return _textos_sem_fonte(spec, columns, rows, question, sql)
