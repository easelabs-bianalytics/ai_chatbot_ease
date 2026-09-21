"""Prompts versionados em arquivo (ADR-0006).

A versão vai em cada resposta: sem ela, não dá para saber com que instruções
um texto foi produzido depois de o prompt mudar.
"""

from pathlib import Path

# v2 (2026-09-21, ADR-0025): investigação de perguntas de porquê e resposta
# em blocos. A v1 fica no repositório: é a versão gravada nas respostas
# anteriores, e a auditoria precisa conseguir lê-la.
PROMPT_VERSION = "planner_v2"
ANSWER_PROMPT_VERSION = "answerer_v2"
# Leitura de imagem (ADR-0024). É um prompt curto de propósito: não leva
# catálogo, schema nem consultas de referência, porque esse caminho não toca
# o banco. São ~350 tokens contra os ~15 mil do planejamento.
IMAGE_PROMPT_VERSION = "leitor_de_imagem_v1"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(nome: str = PROMPT_VERSION) -> str:
    return (PROMPTS_DIR / f"{nome}.md").read_text(encoding="utf-8")
