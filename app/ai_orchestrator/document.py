"""Divide o documento de referência em seções (ADR-0015).

O documento é escrito pelo time de BI em Markdown, com uma seção por tema
(`## 1. Auditoria e Prescrição Médica`, `## 2. Sell Out...`). Mandá-lo
inteiro em toda pergunta custa caro e enche o contexto de regra que não se
aplica; mandar pedaço errado faz a IA perder uma regra. Por isso o corte
mora aqui, é determinístico e tem teste.

Nada neste módulo interpreta o conteúdo: ele só recorta o que o time de BI
escreveu, preservando o texto original — inclusive as regras em negrito, que
são o que mais importa.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from datasource.sql_guard import tables_in

_CABECALHO = re.compile(r"^##\s+(?P<numero>\d+)\.\s+(?P<titulo>.+?)\s*$", re.MULTILINE)
_BLOCO_SQL = re.compile(r"```sql\s*\n.*?```", re.DOTALL)
_TABELA_CITADA = re.compile(r"`([a-z_]+\.[A-Za-z_][A-Za-z0-9_]*)`")

# Nome curto de cada seção, na ordem do documento. Serve de chave em toda a
# aplicação (roteador, registro em AICall, relatório de custo por tema).
CHAVES = ("prescricao", "sell_out", "estoque", "pbm", "forca_vendas")


@dataclass(frozen=True)
class Secao:
    chave: str
    numero: int
    titulo: str
    texto: str
    # Mesma seção sem as consultas de referência: as regras e as tabelas
    # continuam, porque é delas que a IA precisa quando a seção é secundária.
    resumo: str
    tabelas: frozenset
    referencias: tuple

    @property
    def indice(self) -> str:
        """Uma linha para o índice que vai no núcleo comum."""
        return f"- `{self.chave}` — {self.titulo}"


@dataclass(frozen=True)
class Documento:
    preambulo: str
    secoes: tuple

    def por_chave(self, chave: str):
        for secao in self.secoes:
            if secao.chave == chave:
                return secao
        return None

    @property
    def indice(self) -> str:
        return "\n".join(s.indice for s in self.secoes)


def _resumir(texto: str) -> str:
    """Tira as consultas e deixa no lugar o id e o título de cada uma.

    A seção secundária existe para a IA saber as tabelas, as chaves de junção
    e as regras do outro tema; as consultas inteiras seriam o grosso dos
    tokens e ela não vai partir delas."""

    def substituir(match):
        bloco = match.group(0)
        primeira = bloco.splitlines()[1].strip() if len(bloco.splitlines()) > 1 else ""
        return f"(consulta {primeira.lstrip('- ').strip()} — peça esta seção completa se precisar dela)"

    resumido = _BLOCO_SQL.sub(substituir, texto)
    # Linhas em branco seguidas viram uma só: o corte deixa buracos no texto.
    return re.sub(r"\n{3,}", "\n\n", resumido).strip()


def _tabelas(texto: str, referencias) -> frozenset:
    """Tabelas do tema: as citadas no texto com crase e as que aparecem nas
    consultas de referência da seção."""
    citadas = {t.lower() for t in _TABELA_CITADA.findall(texto)}
    for referencia in referencias:
        citadas |= {t.lower() for t in tables_in(referencia.sql)}
    return frozenset(t for t in citadas if "." in t)


def parse_document(texto: str, referencias=()) -> Documento:
    marcas = list(_CABECALHO.finditer(texto))
    if not marcas:
        raise ValueError("documento de referência sem seções '## N. Título'")

    preambulo = texto[: marcas[0].start()].strip()
    secoes = []
    for posicao, marca in enumerate(marcas):
        fim = marcas[posicao + 1].start() if posicao + 1 < len(marcas) else len(texto)
        corpo = texto[marca.start() : fim].strip()
        numero = int(marca.group("numero"))
        chave = CHAVES[numero - 1] if numero <= len(CHAVES) else f"secao_{numero}"
        das_secao = tuple(r for r in referencias if f"-- {r.id} " in corpo)
        secoes.append(
            Secao(
                chave=chave,
                numero=numero,
                titulo=marca.group("titulo"),
                texto=corpo,
                resumo=_resumir(corpo),
                tabelas=_tabelas(corpo, das_secao),
                referencias=tuple(r.id for r in das_secao),
            )
        )

    return Documento(preambulo=preambulo, secoes=tuple(secoes))


@lru_cache(maxsize=4)
def _documento_em_cache(texto: str, referencias) -> Documento:
    return parse_document(texto, referencias)


def get_document(catalog) -> Documento:
    """Documento já recortado, em cache pelo conteúdo — o recorte é caro o
    bastante para não se refazer a cada pergunta, e o catálogo só muda com
    reinício (ADR-0006)."""
    return _documento_em_cache(catalog.references_text, catalog.references)
