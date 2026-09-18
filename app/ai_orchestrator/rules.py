"""Regras determinísticas antes do modelo.

Casos que não precisam de IA: pedido de alteração de dados, tentativa de
trocar as instruções do assistente, pergunta sobre o próprio chatbot e
mensagem sem pergunta nenhuma. Resolver aqui evita gastar duas chamadas de
modelo para responder o óbvio — e, no pedido de escrita e na tentativa de
injeção, garante a recusa antes mesmo de o texto chegar ao modelo
(ADR-0021): defesa que depende só do prompt depende do modelo obedecer.
"""

import re
import unicodedata
from dataclasses import dataclass

from ai_orchestrator import canned
from ai_orchestrator.models import AIReply


@dataclass(frozen=True)
class RuleOutcome:
    rule: str
    decision: str
    reply: str


def _normalize(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", (texto or "").strip().lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")


# Pedido em português ("apague a tabela", "zera os dados") ou o comando SQL
# escrito direto. Exige o objeto junto para não confundir com pergunta
# legítima: "quando a tabela foi atualizada?" não é pedido de escrita.
_PEDIDO_DE_ESCRITA = re.compile(
    r"\b(apag(a|ar|ue)|delet(a|ar|e)|remov(a|er)|exclu(a|ir)|zer(a|ar|e)|"
    r"atualiz(a|ar|e)|alter(a|ar|e)|insir(a|o)|inser(e|ir)|cri(a|ar|e)|"
    r"trunc(a|ar|ue)|dropa?r?)\s+"
    r"(a|o|os|as|essa|esse|todas?|todos?|meu|minha)?\s*"
    r"(tabela|tabelas|registro|registros|linha|linhas|dado|dados|banco|"
    r"coluna|colunas|base|schema)\b"
    r"|\b(delete\s+from|drop\s+table|truncate\s+table|insert\s+into|"
    r"update\s+\w+\s+set|alter\s+table|create\s+table|grant\s+)\b"
)

# Tentativa de reescrever o que o assistente é (ADR-0021). Cada padrão
# exige o alvo junto — "instruções", "regras", "prompt", "papel" — porque
# "ignore" e "sem filtro" sozinhos aparecem em pergunta legítima ("vendas
# sem filtro de canal"). Falso positivo aqui custa uma recusa cordial;
# falso negativo custa o assistente virando outra coisa.
_PADROES_DE_INJECAO = (
    # trocar ou apagar as regras
    r"\b(ignor|esquec|desconsider)\w*\s+(tudo\b[^.?!]{0,25})?"
    r"((as?|os?|sua?s?|seu?s?|todas?|todos?|essas?|esses?)\s+)*"
    r"(instruc\w+|regras\b|orientac\w+|diretriz\w+|prompt\w*)",
    r"\b(ignore|disregard|forget)\s+(all\s+)?(the\s+)?"
    r"(previous|prior|above|your|any)\s+(instruction|rule|prompt)\w*",
    # fazer o assistente mostrar o que é interno
    r"\b(mostr\w+|revel\w+|exib\w+|imprim\w+|repit\w+|transcrev\w+|vaz\w+|"
    r"me\s+(mande|passe|diga|envie|mostre)|qual\s+e|quais\s+sao)\b[^.?!]{0,40}"
    r"\b(system\s*prompt|prompt\s+(do\s+sistema|de\s+sistema|inicial|completo|original)|"
    r"suas?\s+(instruc\w+|regras\s+intern\w+)|"
    r"instruc\w+\s+(do\s+sistema|iniciais|originais|acima))",
    r"\bsystem\s*prompt\b|\bprompt\s+injection\b",
    # trocar de papel
    r"\b(aja|atue|comporte-?se|finja|faca\s+de\s+conta|se\s+passe)\b[^.?!]{0,30}\bcomo\b",
    r"\b(finja|imagine|suponha|pretenda|faca\s+de\s+conta)\s+(que\s+)?(voce|vc)\s+"
    r"(e\b|eh\b|seja\b|fosse\b|nao\s+e\b|trabalha)",
    r"\b(a\s+partir\s+de\s+agora|de\s+agora\s+em\s+diante|agora)\s+(voce|vc)\s+"
    r"(e\b|eh\b|sera|vai\s+ser|nao\s+e\s+mais)",
    r"\b(voce|vc)\s+(nao\s+e\s+mais|agora\s+e\b|agora\s+sera)",
    # "modos" sem regra
    r"\b(modo\s+(desenvolvedor|dev|deus|livre|irrestrito|dan)|developer\s+mode|jailbreak)\b",
    r"\b(responda|fale|aja|atue|funcione|opere|trabalhe)\s+sem\s+(nenhum\w*\s+)?"
    r"(restric\w+|filtro\w*|censura|limitac\w+|regras)",
    # turno falso de sistema colado na mensagem
    r"(^|\n)\s*(system|assistant|developer|administrador)\s*:",
    r"<\|im_start\|>|\[\s*system\s*\]|###\s*system",
)
_TENTATIVA_DE_INJECAO = re.compile("|".join(_PADROES_DE_INJECAO))

_PEDIDO_DE_AJUDA = re.compile(
    r"\b(o que (voce|vc|tu)\s+(sabe|faz|pode|consegue)|"
    r"como (voce|vc)?\s*funciona|para que (voce|vc) serve|"
    r"quais (dados|perguntas|temas|assuntos|informacoes)|"
    r"me ajuda a usar|como usar (voce|vc|isso|aqui))\b|^ajuda$|^help$"
)

_TEM_LETRA = re.compile(r"[a-z]")


def apply_rules(texto: str, catalog) -> RuleOutcome | None:
    """Devolve a resposta determinística, ou None para seguir para a IA."""
    normalizado = _normalize(texto)

    if _PEDIDO_DE_ESCRITA.search(normalizado):
        return RuleOutcome(
            rule="pedido_de_escrita",
            decision=AIReply.Decision.OUT_OF_SCOPE,
            reply=canned.FORA_DE_ESCOPO_ESCRITA,
        )

    if _TENTATIVA_DE_INJECAO.search(normalizado):
        # Fica registrado na auditoria pela regra, para o time de BI ver se
        # alguém está testando os limites do assistente.
        return RuleOutcome(
            rule="tentativa_de_injecao",
            decision=AIReply.Decision.OUT_OF_SCOPE,
            reply=canned.TENTATIVA_DE_INJECAO,
        )

    if _PEDIDO_DE_AJUDA.search(normalizado):
        return RuleOutcome(
            rule="pedido_de_ajuda",
            decision=AIReply.Decision.CONVERSATION,
            reply=canned.ajuda(catalog),
        )

    if not _TEM_LETRA.search(normalizado):
        return RuleOutcome(
            rule="mensagem_sem_pergunta",
            decision=AIReply.Decision.CLARIFY,
            reply=canned.MENSAGEM_SEM_PERGUNTA,
        )

    return None
