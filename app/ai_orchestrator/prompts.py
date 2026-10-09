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
# v2 (ADR-0035): transcreve todo bloco de dado do print, diz o que a pessoa
# quer com ele e se deu para ler. A v1 fica: é a gravada nas respostas antigas.
IMAGE_PROMPT_VERSION = "leitor_de_imagem_v2"
# Regras da planilha anexada (ADR-0031): entram no plano só quando há
# planilha na conversa, depois do perfil dela.
PLANILHA_PROMPT_VERSION = "planilha_v1"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(nome: str = PROMPT_VERSION) -> str:
    return (PROMPTS_DIR / f"{nome}.md").read_text(encoding="utf-8")
