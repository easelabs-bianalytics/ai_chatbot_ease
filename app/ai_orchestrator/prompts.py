"""Prompts versionados em arquivo (ADR-0006).

A versão vai em cada resposta: sem ela, não dá para saber com que instruções
um texto foi produzido depois de o prompt mudar.
"""

from pathlib import Path

PROMPT_VERSION = "planner_v1"
ANSWER_PROMPT_VERSION = "answerer_v1"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(nome: str = PROMPT_VERSION) -> str:
    return (PROMPTS_DIR / f"{nome}.md").read_text(encoding="utf-8")
