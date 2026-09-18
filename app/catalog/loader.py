"""Carrega o catálogo e as consultas de referência (ADR-0006, ADR-0014).

Duas fontes, cada uma com um dono:

- `app/knowledge/catalog.yaml` — lido por máquina pelo validador de SQL;
- `chatbot_bi_referencia_querys.md` — mantido pelo time de BI e injetado
  inteiro no prompt do planejador.

O hash das duas vai em cada resposta (`AIReply.catalog_hash`): é o que diz
com qual conhecimento aquela resposta foi produzida, e o que denuncia um
relatório de validação obsoleto.
"""

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from catalog.errors import CatalogError
from catalog.snapshot import DEFAULT_SNAPSHOT_PATH

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_CATALOG_PATH = BASE_DIR / "app" / "knowledge" / "catalog.yaml"
DEFAULT_REFERENCES_PATH = BASE_DIR / "chatbot_bi_referencia_querys.md"

_REFERENCE_BLOCK = re.compile(r"```sql\s*\n(.*?)```", re.DOTALL)
# O identificador segue o que o time de BI escreve no arquivo (Q10, A01,
# B05...): letra de assunto e número. O que não pode faltar é o próprio
# identificador, porque é ele que a resposta registra como base (ADR-0014).
_REFERENCE_HEADER = re.compile(
    r"^--\s*(?P<id>[A-Za-z]{1,3}\d{1,3})\s*[·.:\-—]\s*(?P<titulo>.+)$"
)


@dataclass(frozen=True)
class ReferenceQuery:
    id: str
    title: str
    sql: str


@dataclass(frozen=True)
class Catalog:
    schemas: frozenset
    blocked_tables: dict
    blocked_columns: dict
    blocked_functions: frozenset
    blocked_function_prefixes: tuple
    max_rows: int
    statement_timeout_ms: int
    rows_to_model: int
    notes: tuple
    references_text: str
    references: tuple
    hash: str
    # Snapshot do schema real (vazio até o primeiro catalog_snapshot).
    schema_text: str = ""
    # Schemas previstos que ainda não existem no banco (ex.: metas).
    future_schemas: frozenset = frozenset()

    def blocked_columns_for(self, table: str) -> frozenset:
        return self.blocked_columns.get(table.lower(), frozenset())

    def has_blocked_columns(self, table: str) -> bool:
        return bool(self.blocked_columns_for(table))


def parse_reference_queries(texto: str) -> tuple:
    """Extrai os blocos ```sql``` do arquivo de referências.

    Cada bloco começa com `-- Q10 · título`. Bloco sem esse cabeçalho é erro
    de catálogo: sem o identificador, a resposta não tem como registrar em
    qual referência se baseou (ADR-0014).
    """
    consultas = []
    for bloco in _REFERENCE_BLOCK.findall(texto):
        linhas = bloco.strip().splitlines()
        cabecalho = _REFERENCE_HEADER.match(linhas[0].strip())
        if cabecalho is None:
            raise CatalogError(
                f"consulta de referência sem cabeçalho '-- Qxx · título': {linhas[0]!r}"
            )
        consultas.append(
            ReferenceQuery(
                id=cabecalho.group("id"),
                title=cabecalho.group("titulo").strip(),
                sql="\n".join(linhas[1:]).strip(),
            )
        )

    if not consultas:
        raise CatalogError("nenhuma consulta de referência encontrada")

    ids = [c.id for c in consultas]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise CatalogError(f"consultas de referência com id repetido: {repetidos}")

    return tuple(consultas)


def _require(dados: dict, chave: str):
    if chave not in dados:
        raise CatalogError(f"catálogo sem a chave obrigatória {chave!r}")
    return dados[chave]


def build_catalog(dados: dict, references_text: str, hash_: str, schema_text: str = "") -> Catalog:
    schemas = frozenset(str(s).lower() for s in _require(dados, "schemas_permitidos"))
    if not schemas:
        raise CatalogError("schemas_permitidos vazio: nenhuma consulta passaria")

    blocked_tables = {}
    for item in dados.get("tabelas_bloqueadas") or []:
        objeto = str(item["objeto"]).lower()
        if "." not in objeto:
            raise CatalogError(f"tabela bloqueada sem schema: {objeto!r}")
        blocked_tables[objeto] = str(item.get("motivo", "")).strip()

    blocked_columns = {}
    for tabela, item in (dados.get("colunas_bloqueadas") or {}).items():
        chave = str(tabela).lower()
        if "." not in chave:
            raise CatalogError(f"tabela de colunas bloqueadas sem schema: {chave!r}")
        colunas = frozenset(str(c).lower() for c in item["colunas"])
        if not colunas:
            raise CatalogError(f"lista de colunas bloqueadas vazia em {chave!r}")
        blocked_columns[chave] = colunas

    limites = _require(dados, "limites")
    notes = tuple(
        (str(n["objeto"]), " ".join(str(n["nota"]).split()))
        for n in dados.get("dicionario") or []
    )

    return Catalog(
        schemas=schemas,
        blocked_tables=blocked_tables,
        blocked_columns=blocked_columns,
        blocked_functions=frozenset(
            str(f).lower() for f in dados.get("funcoes_bloqueadas") or []
        ),
        blocked_function_prefixes=tuple(
            str(p).lower() for p in dados.get("prefixos_de_funcao_bloqueados") or []
        ),
        max_rows=int(_require(limites, "max_linhas")),
        statement_timeout_ms=int(_require(limites, "timeout_ms")),
        rows_to_model=int(_require(limites, "linhas_para_o_modelo")),
        notes=notes,
        references_text=references_text,
        references=parse_reference_queries(references_text),
        hash=hash_,
        schema_text=schema_text,
        future_schemas=frozenset(str(s).lower() for s in dados.get("schemas_futuros") or []),
    )


def load_catalog(
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    references_path: Path = DEFAULT_REFERENCES_PATH,
    snapshot_path: Path | None = DEFAULT_SNAPSHOT_PATH,
) -> Catalog:
    catalog_bytes = Path(catalog_path).read_bytes()
    references_bytes = Path(references_path).read_bytes()
    snapshot_bytes = (
        Path(snapshot_path).read_bytes()
        if snapshot_path is not None and Path(snapshot_path).exists()
        else b""
    )

    try:
        dados = yaml.safe_load(catalog_bytes.decode("utf-8"))
    except yaml.YAMLError as exc:
        raise CatalogError(f"catálogo inválido: {exc}") from exc
    if not isinstance(dados, dict):
        raise CatalogError("catálogo vazio ou mal formado")

    # O snapshot entra no hash: regerá-lo muda o que a IA sabe do banco.
    hash_ = hashlib.sha256(catalog_bytes + references_bytes + snapshot_bytes).hexdigest()
    return build_catalog(
        dados, references_bytes.decode("utf-8"), hash_, snapshot_bytes.decode("utf-8")
    )


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """Catálogo em cache do processo. Alterar os arquivos exige reiniciar —
    o conteúdo muda o comportamento da IA e precisa passar pelos casos
    sintéticos antes (ADR-0006)."""
    return load_catalog()
