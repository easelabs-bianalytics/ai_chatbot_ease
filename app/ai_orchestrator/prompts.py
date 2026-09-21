"""Prompts versionados em arquivo (ADR-0006).

A versão vai em cada resposta: sem ela, não dá para saber com que instruções
um texto foi produzido depois de o prompt mudar.
"""

from pathlib import Path

PROMPT_VERSION = "planner_v1"
ANSWER_PROMPT_VERSION = "answerer_v1"
# Leitura de imagem (ADR-0024). É um prompt curto de propósito: não leva
# catálogo, schema nem consultas de referência, porque esse caminho não toca
# o banco. São ~350 tokens contra os ~15 mil do planejamento.
IMAGE_PROMPT_VERSION = "leitor_de_imagem_v1"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(nome: str = PROMPT_VERSION) -> str:
    return (PROMPTS_DIR / f"{nome}.md").read_text(encoding="utf-8")
