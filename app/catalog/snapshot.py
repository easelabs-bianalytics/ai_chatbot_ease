"""Snapshot do schema real do banco de negócio (ADR-0006, ADR-0014).

A IA só escreve SQL certo se conhecer as colunas de verdade. As consultas de
referência mostram parte delas; o resto vem daqui, gerado do próprio banco
com o usuário de leitura, e não escrito à mão.

Duas escolhas deliberadas:

- a leitura é no pg_catalog e não no information_schema, porque este último
  não lista views materializadas — e o banco de negócio tem várias;
- tabelas e colunas bloqueadas pelo catálogo ficam de fora do arquivo: a IA
  nem fica sabendo que existem, o que é mais forte do que proibir o uso.
"""

import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from catalog.errors import CatalogError

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_SNAPSHOT_PATH = BASE_DIR / "app" / "knowledge" / "schema_snapshot.md"

_NOME_SIMPLES = re.compile(r"^[a-z_][a-z0-9_]*$")

_TIPOS = {"r": "tabela", "p": "tabela", "v": "view", "m": "view materializada", "f": "tabela externa"}


def _sql_relacoes(schemas) -> str:
    # O executor não recebe parâmetros, então a lista entra no texto. Ela vem
    # do catálogo (e não do usuário ou da IA), e mesmo assim cada nome é
    # conferido antes.
    for schema in schemas:
        if not _NOME_SIMPLES.match(schema):
            raise CatalogError(f"nome de schema inesperado no catálogo: {schema!r}")
    lista = ", ".join(f"'{s}'" for s in sorted(schemas))
    return f"""
        SELECT n.nspname, c.relname, c.relkind, a.attname,
               format_type(a.atttypid, a.atttypmod)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        WHERE n.nspname IN ({lista})
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND NOT c.relispartition
          AND has_table_privilege(c.oid, 'SELECT')
        ORDER BY n.nspname, c.relname, a.attnum
    """


def ler_relacoes(executor, catalog) -> "OrderedDict":
    """{"schema.tabela": {"tipo": ..., "colunas": [(nome, tipo), ...]}} do
    que o usuário configurado enxerga de fato."""
    resultado = executor.run(_sql_relacoes(catalog.schemas))
    relacoes = OrderedDict()
    for schema, tabela, tipo, coluna, tipo_coluna in resultado.rows:
        chave = f"{schema}.{tabela}"
        item = relacoes.setdefault(
            chave, {"tipo": _TIPOS.get(tipo, tipo), "colunas": []}
        )
        item["colunas"].append((coluna, tipo_coluna))
    return relacoes


def _identificador(nome: str) -> str:
    """Coluna com maiúscula ou símbolo sai entre aspas, do jeito que a IA
    precisa escrever no SQL ("STATUS_TRN", "R$_PDV_MERCADO")."""
    return nome if _NOME_SIMPLES.match(nome) else f'"{nome}"'


def render_snapshot(relacoes, catalog, gerado_em=None) -> tuple:
    """Devolve (texto, resumo). O texto é o que vai para o arquivo."""
    gerado_em = gerado_em or datetime.now().strftime("%Y-%m-%d %H:%M")
    removidas_tabelas = 0
    removidas_colunas = 0
    por_schema = OrderedDict()

    for chave in sorted(relacoes):
        if chave.lower() in catalog.blocked_tables:
            removidas_tabelas += 1
            continue
        bloqueadas = catalog.blocked_columns_for(chave)
        colunas = []
        for nome, tipo in relacoes[chave]["colunas"]:
            if nome.lower() in bloqueadas:
                removidas_colunas += 1
                continue
            colunas.append(f"{_identificador(nome)} {tipo}")
        por_schema.setdefault(chave.split(".", 1)[0], []).append(
            f"- `{chave}` ({relacoes[chave]['tipo']}): {', '.join(colunas)}"
        )

    linhas = [
        "# Schema do banco de negócio",
        "",
        f"> Gerado por `manage.py catalog_snapshot` em {gerado_em}, com o usuário",
        "> somente leitura. Não edite à mão: rode o comando de novo.",
        ">",
        "> Tabelas e colunas bloqueadas pelo catálogo não aparecem aqui de propósito.",
        "",
    ]
    for schema, itens in por_schema.items():
        linhas += [f"## {schema}", "", *itens, ""]

    resumo = {
        "schemas": len(por_schema),
        "relacoes": sum(len(v) for v in por_schema.values()),
        "tabelas_omitidas": removidas_tabelas,
        "colunas_omitidas": removidas_colunas,
    }
    return "\n".join(linhas), resumo
