"""Conferência dos filtros de nome contra o cadastro, antes de executar.

Incidente de 2026-10-19 (conversa 118): o diretor escreveu "cuibá", a IA
filtrou `pdvs.cidade ILIKE '%CUIBA%'`, e esse pedaço não casa CUIABA — casa
CARAPICUIBA (SP). A consulta rodou sem erro, devolveu 1, 2 e 1 unidades, e a
resposta chamou de Cuiabá os números de Carapicuíba. Na pergunta seguinte,
já com o nome certo, a IA reaproveitou a consulta da conversa e repetiu o
erro. Nada na resposta denunciava o problema.

O documento de referência já manda buscar nome por um pedaço e perguntar
quando ele trouxer mais de um; o que faltava era alguém conferir. Esta
camada é determinística: para cada filtro de nome numa coluna do catálogo
(`nomes_conferidos`), lista os valores do cadastro que o filtro pega e
recusa a consulta — com o motivo e os nomes certos, para a correção única
(ADR-0014) — quando:

- o filtro não pega nenhum nome do cadastro (grafia errada, acento, caixa);
- pega mais de um nome diferente (`'%CARLOS%'`: dois representantes);
- pega um nome só, mas que não é o pedido: o pedaço está dentro de outro
  nome e existe um nome bem mais parecido com o que foi escrito
  (`'%CUIBA%'` → CARAPICUIBA, quando o parecido é CUIABA);
- o nome existe em mais de uma UF e a consulta não filtra a UF.

Filtro com `=` ou `IN` e o nome exato do cadastro passa: é assim que a
correção diz "quero estes", inclusive mais de um de propósito.
"""

import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

DIALETO = "postgres"
# Nome "bem mais parecido" com o que foi escrito: CUIBA × CUIABA dá 0,91;
# CUIBA × CARAPICUIBA, 0,62.
PARECIDO = 0.8
SUGESTOES = 4


@dataclass(frozen=True)
class NomeConferido:
    """Uma coluna de nome do catálogo: `tabela` com schema, `coluna`, a
    coluna de UF da mesma tabela (vazia quando não há) e como chamar o
    valor na mensagem ("cidade", "representante")."""

    tabela: str
    coluna: str
    uf: str = ""
    rotulo: str = "nome"

    @property
    def chave(self) -> str:
        return f"{self.tabela}.{self.coluna}"

    @property
    def sql_dos_valores(self) -> str:
        colunas = f"{self.coluna}, {self.uf}" if self.uf else self.coluna
        return (f"SELECT DISTINCT {colunas} FROM {self.tabela} "
                f"WHERE {self.coluna} IS NOT NULL")


def normalizar(texto) -> str:
    """Maiúsculas, sem acento e sem espaço sobrando — como o cadastro grava
    (`cddd.forca_vendas.desc_territorio` tem até tab no fim do nome)."""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.upper().split())


def _regex_do_like(padrao: str) -> re.Pattern:
    partes = []
    for letra in padrao:
        partes.append(".*" if letra == "%" else "." if letra == "_" else re.escape(letra))
    return re.compile("^" + "".join(partes) + "$", re.IGNORECASE | re.DOTALL)


def _miolo(padrao: str) -> str:
    """O que o usuário escreveu, sem os curingas do LIKE."""
    return normalizar(padrao.replace("%", " ").replace("_", " "))


def _coluna(no):
    """A coluna dentro de upper()/lower()/trim(), ou None."""
    return _coluna_e_funcao(no)[0]


def _coluna_e_funcao(no):
    """(coluna, se veio dentro de upper()/lower()/trim())."""
    embrulhada = False
    while isinstance(no, (exp.Upper, exp.Lower, exp.Trim, exp.Paren)):
        embrulhada = embrulhada or not isinstance(no, exp.Paren)
        no = no.this
    return (no, embrulhada) if isinstance(no, exp.Column) else (None, False)


def _texto(no):
    return no.this if isinstance(no, exp.Literal) and no.is_string else None


def _negado(no) -> bool:
    if no.args.get("negate"):
        return True   # NOT ILIKE / NOT LIKE: o sqlglot marca no próprio nó
    pai = no.parent
    while isinstance(pai, exp.Paren):
        pai = pai.parent
    return isinstance(pai, exp.Not)


def _tabelas_por_apelido(arvore) -> dict:
    apelidos = {}
    for tabela in arvore.find_all(exp.Table):
        if not tabela.name or not tabela.db:
            continue
        nome = f"{tabela.db}.{tabela.name}".lower()
        apelidos[(tabela.alias_or_name or "").lower()] = nome
        apelidos.setdefault(tabela.name.lower(), nome)
    return apelidos


def _conferido(coluna, apelidos, conferidos) -> NomeConferido | None:
    nome = (coluna.name or "").lower()
    if coluna.table:
        tabela = apelidos.get(coluna.table.lower())
        candidatos = [c for c in conferidos if c.tabela == tabela and c.coluna == nome]
    else:
        presentes = set(apelidos.values())
        candidatos = [c for c in conferidos if c.coluna == nome and c.tabela in presentes]
    return candidatos[0] if len(candidatos) == 1 else None


def filtros(sql: str, conferidos) -> list:
    """Os filtros positivos de nome da consulta: (conferido, operador, valor).
    Operador é "like" (LIKE/ILIKE, valor é o padrão), "=" (= e IN, valor
    exato) ou "=~" (= e IN com a coluna em upper()/lower()/trim(): vale o
    nome sem caixa e sem espaço sobrando)."""
    try:
        arvore = sqlglot.parse_one(sql, read=DIALETO)
    except sqlglot.ParseError:
        return []
    apelidos = _tabelas_por_apelido(arvore)
    achados = []
    for no in arvore.walk():
        if isinstance(no, (exp.Like, exp.ILike, exp.EQ)):
            lados = [(no.this, no.expression), (no.expression, no.this)]
            for lado_coluna, lado_valor in lados:
                (coluna, embrulhada), valor = _coluna_e_funcao(lado_coluna), _texto(lado_valor)
                if coluna is None or valor is None or _negado(no):
                    continue
                conf = _conferido(coluna, apelidos, conferidos)
                if conf:
                    igual = "=~" if embrulhada else "="
                    achados.append((conf, igual if isinstance(no, exp.EQ) else "like", valor))
                break
        elif isinstance(no, exp.In) and not _negado(no):
            coluna, embrulhada = _coluna_e_funcao(no.this)
            valores = [_texto(v) for v in no.expressions]
            if coluna is None or not valores or any(v is None for v in valores):
                continue
            conf = _conferido(coluna, apelidos, conferidos)
            if conf:
                achados.extend((conf, "=~" if embrulhada else "=", v) for v in valores)
    return achados


def _ufs_filtradas(sql: str, conf: NomeConferido):
    """As UFs que a consulta fixa (`uf = 'SP'`, `uf IN (...)`), em
    maiúsculas; conjunto vazio se filtra a UF de outro jeito (parâmetro,
    subconsulta); None se não filtra."""
    try:
        arvore = sqlglot.parse_one(sql, read=DIALETO)
    except sqlglot.ParseError:
        return None
    ufs, filtra = set(), False
    for no in arvore.find_all(exp.EQ, exp.In, exp.Like, exp.ILike):
        if isinstance(no, exp.In):
            pares = [(no.this, v) for v in no.expressions]
        else:
            pares = [(no.this, no.expression), (no.expression, no.this)]
        for lado, valor in pares:
            coluna = _coluna(lado)
            if coluna is None or (coluna.name or "").lower() != conf.uf:
                continue
            filtra = True
            if _texto(valor) is not None:
                ufs.add(_texto(valor).strip().upper())
    return ufs if filtra else None


def _rotulo(nome, ufs) -> str:
    return f"{nome} ({', '.join(sorted(ufs))})" if ufs else nome


def _sugestoes(miolo, por_nome) -> list:
    nomes = list(por_nome)
    normalizados = {normalizar(n): n for n in nomes}
    parecidos = difflib.get_close_matches(miolo, list(normalizados), n=SUGESTOES, cutoff=0.6)
    return [_rotulo(normalizados[p], por_nome[normalizados[p]]) for p in parecidos]


def avaliar(conf: NomeConferido, operador: str, valor: str, linhas, ufs_filtradas=None) -> str:
    """O motivo da recusa para um filtro, ou "" se ele está certo.

    `ufs_filtradas`: as UFs que a consulta fixa — só os nomes delas contam
    (`'%SAO JOSE%' AND uf = 'SC'` não pega SAO JOSE DOS CAMPOS); vazio
    quando filtra a UF sem valor fixo; None quando não filtra."""
    filtra_uf = ufs_filtradas is not None
    por_nome, gravado = {}, {}
    for linha in linhas:
        if ufs_filtradas and len(linha) > 1 and str(linha[1]).strip().upper() not in ufs_filtradas:
            continue
        nome = " ".join(str(linha[0]).split())
        gravado.setdefault(nome, set()).add(str(linha[0]))
        ufs = por_nome.setdefault(nome, set())
        if conf.uf and len(linha) > 1 and linha[1]:
            ufs.add(str(linha[1]).strip())
    if not por_nome:
        return ""

    escrito = f"{conf.coluna} {'ILIKE' if operador == 'like' else '='} '{valor}'"
    if operador == "=":
        casados = [n for n in por_nome if valor in gravado[n]]
        miolo = normalizar(valor)
        sobra = [n for n in por_nome if not casados and n == valor.strip()]
        if sobra:
            return (f"o filtro {escrito} não pega nada: o cadastro grava {sorted(gravado[sobra[0]])[0]!r}, "
                    f"com espaço sobrando. Compare com TRIM({conf.coluna}) = '{valor.strip()}'.")
    elif operador == "=~":
        casados = [n for n in por_nome if normalizar(n) == normalizar(valor)]
        miolo = normalizar(valor)
    else:
        padrao = _regex_do_like(valor)
        casados = [n for n in por_nome if padrao.match(n)]
        miolo = _miolo(valor)
    exato = f"use {conf.coluna} = '<nome exato>'"

    if not casados:
        sugestoes = _sugestoes(miolo, por_nome)
        dica = f" Os nomes mais parecidos no cadastro: {'; '.join(sugestoes)}." if sugestoes else ""
        return (f"o filtro {escrito} não pega nenhuma {conf.rotulo} do cadastro ({conf.tabela}).{dica} "
                f"O cadastro grava em maiúsculas e sem acento: {exato}. Se não der para saber qual "
                f"{conf.rotulo} o usuário quis, pergunte mostrando as opções.")

    if len(casados) > 1:
        lista = "; ".join(_rotulo(n, por_nome[n]) for n in sorted(casados)[:8])
        mais = f" e mais {len(casados) - 8}" if len(casados) > 8 else ""
        return (f"o filtro {escrito} pega {len(casados)} {conf.rotulo}s diferentes: {lista}{mais}. "
                f"Somar todas daria o número de outra coisa. Se o usuário quis uma, {exato}; se quis "
                f"mais de uma, liste-as com IN; se não der para saber, pergunte mostrando as opções.")

    nome = casados[0]
    if normalizar(nome) != miolo:
        melhores = [s for s in difflib.get_close_matches(miolo, [normalizar(n) for n in por_nome],
                                                          n=SUGESTOES, cutoff=PARECIDO)
                    if s != normalizar(nome)]
        if melhores:
            originais = {normalizar(n): n for n in por_nome}
            certos = "; ".join(_rotulo(originais[m], por_nome[originais[m]]) for m in melhores)
            return (f"o filtro {escrito} pega só {_rotulo(nome, por_nome[nome])}, que não é o nome "
                    f"escrito: '{miolo}' é pedaço de outro nome. O nome do cadastro mais parecido com "
                    f"'{miolo}' é {certos}. Confira o que o usuário pediu e {exato}.")

    ufs = por_nome[nome]
    if conf.uf and len(ufs) > 1 and not filtra_uf:
        return (f"{conf.rotulo} {nome} existe em {len(ufs)} UFs ({', '.join(sorted(ufs))}) e a consulta "
                f"não filtra {conf.uf}: o resultado somaria lugares diferentes. Filtre também "
                f"{conf.uf} = '<UF>'; se o usuário não disse qual, pergunte.")
    return ""


def conferir(sql: str, conferidos, executor) -> str:
    """Motivo para recusar a consulta, ou "" se os filtros de nome estão
    certos. Se o cadastro não puder ser lido, não recusa: a conferência é
    uma proteção a mais, nunca o motivo de uma pergunta ficar sem resposta."""
    achados = filtros(sql, conferidos)
    if not achados:
        return ""
    motivos = []
    for conf, operador, valor in achados:
        try:
            linhas = executor.valores_cadastrados(conf.chave, conf.sql_dos_valores)
        except Exception:  # noqa: BLE001 — o cadastro fora do ar não pode derrubar a resposta
            logger.warning("Não deu para ler o cadastro de %s para conferir o filtro", conf.chave, exc_info=True)
            continue
        if not linhas:
            continue
        motivo = avaliar(conf, operador, valor, linhas, _ufs_filtradas(sql, conf) if conf.uf else set())
        if motivo and motivo not in motivos:
            motivos.append(motivo)
    return " ".join(motivos)
