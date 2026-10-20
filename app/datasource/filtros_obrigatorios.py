"""Filtros que toda consulta a certas tabelas tem de ter (catálogo: `filtros_obrigatorios`).

Sell In realizado é só `"Utilização"` = `Venda` ou `Venda - PBM` (decisão do
Rubens, 2026-10-20). Hoje a `estoque_redes.fato_sell_in` só tem essas duas,
mas as próximas cargas vão trazer outros tipos de utilização (devolução,
bonificação, remessa...), e uma consulta sem o filtro passaria a contá-los
como venda — sem erro nenhum, com o faturamento maior. O documento manda
filtrar; esta camada garante: cada uso da tabela na consulta precisa do
filtro no próprio WHERE, como condição do AND (não dentro de um OR), só com
os valores permitidos. Faltou, a consulta é recusada com o motivo, para a
correção única (ADR-0014).

Determinístico e sem banco: roda dentro do validador (`sql_guard`).
"""

from dataclasses import dataclass

from sqlglot import exp


@dataclass(frozen=True)
class FiltroObrigatorio:
    tabela: str          # schema.tabela, minúsculo
    coluna: str          # como está no banco ("Utilização")
    valores: tuple       # os únicos aceitos
    motivo: str = ""     # por que, na mensagem para a correção

    @property
    def filtro_sql(self) -> str:
        lista = ", ".join("'" + v.replace("'", "''") + "'" for v in self.valores)
        return f'"{self.coluna}" IN ({lista})'


def _nome(tabela: exp.Table) -> str:
    return f"{tabela.db}.{tabela.name}".lower() if tabela.db else (tabela.name or "").lower()


def _condicoes_do_and(where):
    if where is None:
        return []
    pilha, condicoes = [where.this], []
    while pilha:
        no = pilha.pop()
        while isinstance(no, exp.Paren):
            no = no.this
        if isinstance(no, exp.And):
            pilha.extend([no.this, no.expression])
        else:
            condicoes.append(no)
    return condicoes


def _texto(no):
    return no.this if isinstance(no, exp.Literal) and no.is_string else None


def _restringe(condicao, filtro: FiltroObrigatorio, apelido: str, sozinha: bool) -> bool:
    """A condição limita a coluna aos valores permitidos?"""
    if isinstance(condicao, exp.EQ):
        pares = [(condicao.this, [condicao.expression]), (condicao.expression, [condicao.this])]
    elif isinstance(condicao, exp.In) and not condicao.args.get("query"):
        pares = [(condicao.this, condicao.expressions)]
    else:
        return False
    for coluna, valores in pares:
        if not isinstance(coluna, exp.Column) or coluna.name != filtro.coluna:
            continue
        if coluna.table and coluna.table.lower() != apelido:
            continue
        if not coluna.table and not sozinha:
            continue
        textos = [_texto(v) for v in valores]
        return bool(textos) and all(t is not None and t in filtro.valores for t in textos)
    return False


def conferir(arvore, filtros) -> str:
    """Motivo da recusa, ou "" se todo uso das tabelas tem o filtro."""
    if not filtros:
        return ""
    por_tabela = {f.tabela: f for f in filtros}
    for tabela in arvore.find_all(exp.Table):
        filtro = por_tabela.get(_nome(tabela))
        if filtro is None:
            continue
        select = tabela.find_ancestor(exp.Select)
        if select is None:
            continue
        apelido = (tabela.alias_or_name or "").lower()
        # Coluna sem qualificador só conta se a tabela é a única do FROM.
        sozinha = len([t for t in select.find_all(exp.Table) if t.find_ancestor(exp.Select) is select]) == 1
        if not any(_restringe(c, filtro, apelido, sozinha) for c in _condicoes_do_and(select.args.get("where"))):
            onde = f"{tabela.alias_or_name}." if tabela.alias and not sozinha else ""
            return (f"toda consulta a {filtro.tabela} precisa do filtro {onde}{filtro.filtro_sql} no WHERE "
                    f"de cada uso da tabela (inclusive em CTE e subconsulta), como condição do AND. "
                    f"{filtro.motivo}").strip()
    return ""
