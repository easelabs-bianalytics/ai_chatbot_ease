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


# Princípio das regras daqui: só o INEQUÍVOCO é decidido sem o modelo.
# Errar para o lado do modelo custa centavos (ele mesmo recusa escrita e
# responde "o que você faz"); errar para o lado da regra deixa a pessoa sem
# resposta — e sem entender por quê. Quem garante que nada escreve no banco
# é o validador (`sql_guard`) e o usuário somente leitura (ADR-0008), não
# esta regra.
#
# Pedido de escrita: só o inequívoco — o comando SQL escrito direto, ou um
# verbo de escrita com o BANCO como alvo dito ("apague a tabela de pdvs do
# banco", "atualize os registros no banco de dados"). Em 2026-10-02, frases
# como "apague a tabela e mostre só o gráfico", "exclua os dados de setembro
# da comparação" e "delete os registros duplicados da análise" — pedidos
# sobre a RESPOSTA — eram recusadas como escrita. O resto vai ao modelo, que
# recusa escrita de verdade (planejador, seção 6).
_ALVO_NO_BANCO = (
    r"(?:banco(?:\s+de\s+dados)?|base\s+de\s+dados|database|schema|"
    r"(?:no|do|na|da)\s+sistema|tabelas?\s+\w+\.\w+)"
)
_PEDIDO_DE_ESCRITA = re.compile(
    # Só o verbo como PEDIDO (imperativo, infinitivo): "foi atualizada no
    # banco" é pergunta, não ordem.
    r"\b(?:apag(?:a|ar|ue|uem)|delet(?:a|ar|e|em)|exclu(?:a|ir|i|am)|remov(?:a|er|e|am)|zer(?:a|ar|e)|"
    r"insir(?:a|o)|inser(?:e|ir)|trunc(?:a|ar|ue)|drop(?:e|ar)?|atualiz(?:a|ar|e|em)|alter(?:a|ar|e)|"
    r"modifi(?:ca|car|que)|edit(?:a|ar|e)|cri(?:a|ar|e)|grav(?:a|ar|e))\b"
    r"[^.?!]{0,50}\b" + _ALVO_NO_BANCO + r"\b"
    r"|\b(delete\s+from|drop\s+table|truncate\s+table|insert\s+into|"
    r"update\s+\w+\s+set|alter\s+table|create\s+table|grant\s+)\b"
)

# Tentativa de reescrever o que o assistente é (ADR-0021). Cada padrão
# exige o alvo junto — "instruções", "regras", "prompt", "papel" — porque
# "ignore" e "sem filtro" sozinhos aparecem em pergunta legítima ("vendas
# sem filtro de canal"). Falso positivo aqui custa uma recusa cordial;
# falso negativo custa o assistente virando outra coisa.
# Só o inequívoco aqui também (2026-10-02). "Atue como um analista sênior",
# "imagine que você é o gerente regional", "agora você é meu analista",
# "ignore as regras de corte do mês parcial" e "desconsidere as instruções da
# resposta anterior" são jeitos comuns de pedir ANÁLISE, e eram recusados
# como injeção. Ficam os sinais que só aparecem em ataque: mirar as
# instruções DO ASSISTENTE, pedir o prompt, negar o papel, pedir para operar
# sem regras, "modo desenvolvedor" e turno falso de sistema. O planejador
# continua instruído contra o resto (ADR-0021).
_ALVO_INSTRUCAO = r"(?:instruc\w+|regras\b|orientac\w+|diretriz\w+|prompt\w*)"
_PADROES_DE_INJECAO = (
    # apagar as instruções do assistente — as dele, não uma regra de negócio
    r"\b(?:ignor|esquec|desconsider)\w*\s+(?:(?:todas?|todos?|as|os)\s+)*"
    r"(?:(?:suas?|seus?)\s+" + _ALVO_INSTRUCAO + r"|" + _ALVO_INSTRUCAO +
    r"\s+(?:anteriores|acima|iniciais|originais|do\s+sistema\b(?!\s+d[eo])|de\s+sistema|que\s+(?:te|lhe|voce)\s+\w+))",
    r"\b(?:esquec|ignor|desconsider)\w*\s+tudo\s+(?:o\s+)?que\s+(?:te|lhe)\s+(?:disseram|falaram|ensinaram|passaram|deram)",
    r"\b(ignore|disregard|forget)\s+(all\s+)?(the\s+)?"
    r"(previous|prior|above|your|any)\s+(instruction|rule|prompt)\w*",
    # fazer o assistente mostrar o que é interno
    r"\b(mostr\w+|revel\w+|exib\w+|imprim\w+|repit\w+|transcrev\w+|vaz\w+|"
    r"me\s+(mande|passe|diga|envie|mostre)|qual\s+e|quais\s+sao)\b[^.?!]{0,40}"
    r"\b(system\s*prompt|prompt\s+(do\s+sistema|de\s+sistema|inicial|completo|original)|"
    r"suas?\s+(instruc\w+|regras\s+intern\w+)|"
    r"instruc\w+\s+(do\s+sistema\b(?!\s+d[eo])|iniciais|originais|acima))",
    r"\bsystem\s*prompt\b|\bprompt\s+injection\b",
    # negar o papel, ou trocá-lo por um sem regras
    r"\bfinja\s+(?:que\s+)?(?:voce|vc)\s+(?:e|eh|seja|fosse)\b",
    r"\b(?:voce|vc)\s+nao\s+e\s+mais\b",
    r"\b(?:a\s+partir\s+de\s+agora|de\s+agora\s+em\s+diante|agora)\s+(?:voce|vc)\s+"
    r"(?:e|eh|sera|vai\s+ser)\b[^.?!]{0,60}\bsem\s+(?:nenhum\w*\s+)?(?:restric|filtro|regra|limit|censura)",
    # "modos" sem regra
    r"\b(modo\s+(desenvolvedor|dev|deus|livre|irrestrito|dan)|developer\s+mode|jailbreak)\b",
    r"\b(responda|fale|aja|atue|funcione|opere|trabalhe)\s+sem\s+(nenhum\w*\s+)?"
    r"(restric\w+|filtro\w*|censura|limitac\w+|regras)",
    # turno falso de sistema colado na mensagem
    r"(^|\n)\s*(system|assistant|developer|administrador)\s*:",
    r"<\|im_start\|>|\[\s*system\s*\]|###\s*system",
)
_TENTATIVA_DE_INJECAO = re.compile("|".join(_PADROES_DE_INJECAO))

# Pedido de ajuda: a mensagem INTEIRA é sobre o próprio Jarvis. Antes bastava
# "o que você consegue" em qualquer ponto da frase, e em 2026-09-30 (conversa
# 45) "Analisando o desempenho de 2026 da Ease Labs, o que você consegue tirar
# como insight?" — e a mesma com "aprendizado" — voltaram com a lista de
# temas, de graça e em 0 ms, sem nunca chegar ao modelo. (Em 2026-09-18 já
# tinha sido "o que pode ter causado a queda".) Pergunta que segue para outra
# coisa depois de "o que você consegue" é pergunta de negócio.
_SAUDACAO = r"(?:(?:oi|ola|bom dia|boa tarde|boa noite|e ai|jarvis|amigo|por favor)[\s,!.]*)*"
_SOBRE_O_JARVIS = (
    r"(?:o que|que tipo de coisa|que coisas?|quais coisas)\s+(?:voce|vc|tu)\s+(?:sabe|faz|pode|consegue)"
    r"(?:\s+(?:fazer|responder|consultar|analisar|me dizer|me mostrar|me ajudar|ajudar|me responder))?"
    r"(?:\s+(?:aqui|por mim|pra mim|para mim|com isso))?",
    r"como\s+(?:voce|vc|o jarvis)?\s*funciona",
    r"para que\s+(?:voce|vc|o jarvis)\s+serve",
    r"quais\s+(?:dados|perguntas|temas|assuntos|informacoes)\s+(?:voce|vc)\s+"
    r"(?:tem|sabe|responde|conhece|cobre|consegue responder|acessa)",
    r"quais\s+(?:dados|perguntas|temas|assuntos|informacoes)(?:\s+tem)?",
    r"(?:me )?ajuda a usar(?:\s+(?:voce|vc|o jarvis|isso))?",
    r"como\s+(?:eu\s+)?(?:uso|usar)\s+(?:voce|vc|isso|aqui|o jarvis)",
    r"ajuda", r"help",
)
_PEDIDO_DE_AJUDA = re.compile(
    rf"^{_SAUDACAO}(?:{'|'.join(_SOBRE_O_JARVIS)})[\s?!.]*$"
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


# "Pegue essa base que será enviada a seguir e cruze…", sem anexo: a resposta
# é "pode enviar". Na conversa 82 (2026-10-07) isso passou pelo planejador e
# custou US$ 0,14 para dizer o óbvio. O pedido fica no histórico, e quem o
# executa é a mensagem com o arquivo. Só o inequívoco: o arquivo citado E o
# envio no futuro dito ("será enviada", "vou te mandar", "envio a seguir").
# "Vou enviar essa planilha para a diretoria" não é aviso de anexo.
_ARQUIVO = r"\b(?:planilha|base|arquivo|tabela|excel|xlsx|csv|lista|print|imagem|foto)s?\b"
_ENVIO_A_SEGUIR = (
    r"(?:\b(?:sera|serao|vai ser|vao ser)\s+(?:enviad|mandad|anexad|encaminhad|compartilhad)\w*"
    r"|\b(?:vou|irei|ja vou)\s+(?:te|lhe)\s+(?:enviar|mandar|passar|encaminhar)"
    r"|\b(?:enviad\w*|mandad\w*|anexad\w*|envio|mando|anexo|vem|vai|chega)\s+"
    r"(?:a seguir|em seguida|ja ja|na proxima mensagem|logo mais|daqui a pouco))"
)
_ARQUIVO_A_SEGUIR = re.compile(rf"{_ARQUIVO}.{{0,80}}?{_ENVIO_A_SEGUIR}|{_ENVIO_A_SEGUIR}.{{0,40}}?{_ARQUIVO}")


def arquivo_a_seguir(texto: str) -> RuleOutcome | None:
    """Aviso de que o arquivo vem na próxima mensagem. Quem chama confere
    que esta mensagem não trouxe anexo."""
    if not _ARQUIVO_A_SEGUIR.search(_normalize(texto)):
        return None
    return RuleOutcome(
        rule="arquivo_a_seguir",
        decision=AIReply.Decision.CLARIFY,
        reply=canned.ARQUIVO_A_SEGUIR,
    )
