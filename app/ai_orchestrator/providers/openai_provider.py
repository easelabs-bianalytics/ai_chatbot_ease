"""Provedor real: OpenAI GPT-5.6 (ADR-0016).

Duas etapas, dois modelos: `gpt-5.6-terra` escreve a consulta (é onde o erro
é caro e invisível) e `gpt-5.6-luna` redige a resposta (a checagem de
ancoragem cobre o risco, e ele custa dez vezes menos).

As duas chamadas usam saída estruturada: o orquestrador precisa de campos,
não de texto livre, e um JSON quebrado no meio da madrugada não pode virar
uma resposta sem consulta.

O contexto vem de `context.py`, recortado por tema (ADR-0015), e o
`prompt_cache_key` é o tema — assim perguntas seguidas do mesmo assunto
reaproveitam o prefixo em cache, que custa um décimo.
"""

import json
import logging
import os
import time
from datetime import date

from pydantic import BaseModel, Field

from ai_orchestrator.context import (
    montar_contexto_da_resposta,
    montar_contexto_do_plano,
)
from ai_orchestrator.prompts import ANSWER_PROMPT_VERSION, PROMPT_VERSION, load_prompt
from ai_orchestrator.providers.base import (
    AIProvider,
    AIProviderError,
    AIQuotaExceeded,
    AIUsage,
    Answer,
    AnswerRequest,
    Plan,
    PlanRequest,
)
from catalog.loader import get_catalog

logger = logging.getLogger(__name__)

MODELO_PLANO = "gpt-5.6-terra"
MODELO_RESPOSTA = "gpt-5.6-luna"

# US$ por milhão de tokens: entrada, entrada em cache, saída.
#
# Calibrado contra a fatura, não contra a tabela publicada: em 2026-09-17 a
# página de preços dava US$ 2,00 de entrada para o Terra, e com esse valor o
# total calculado deu US$ 0,955 enquanto o painel da OpenAI marcava US$ 1,16.
# Com US$ 2,50 de entrada a conta fecha em US$ 1,159. Preço subestimado é
# pior que preço ausente: ele vira teto de gasto que não segura nada.
# Reconferir sempre que a fatura divergir do relatório.
PRECOS = {
    "gpt-5.6-sol": (4.00, 0.40, 20.00),
    "gpt-5.6-terra": (2.50, 0.25, 12.00),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
}

_INTENCOES = frozenset(
    {
        Plan.Intent.ANSWER_WITH_DATA,
        Plan.Intent.CLARIFY,
        Plan.Intent.UNKNOWN,
        Plan.Intent.OUT_OF_SCOPE,
        Plan.Intent.CONVERSATION,
    }
)

MAX_TOKENS_PLANO = 8000
MAX_TOKENS_RESPOSTA = 2000


class PlanoEstruturado(BaseModel):
    intent: str = Field(description="answer_with_data, conversation, clarify, unknown ou out_of_scope")
    sql: str = Field(default="", description="a consulta, vazia quando não houver")
    reference_query_id: str = Field(default="", description="id da referência usada como base")
    clarification_question: str = Field(default="", description="pergunta ao usuário")
    user_message: str = Field(default="", description="texto ao usuário em conversation, unknown e out_of_scope")
    reason: str = Field(default="", description="por que esta decisão e esta consulta")
    excel: bool = Field(default=False, description="true se o usuário pediu os dados em Excel, planilha ou arquivo")


class GraficoEstruturado(BaseModel):
    tipo: str = Field(default="nenhum", description="linha, barras, barras_horizontais ou nenhum")
    x: str = Field(default="", description="nome exato da coluna do resultado para o eixo X")
    series: list[str] = Field(default_factory=list, description="nomes exatos de 1 a 3 colunas numéricas")
    titulo: str = Field(default="", description="título curto do gráfico")


class RespostaEstruturada(BaseModel):
    reply: str = Field(description="a resposta ao usuário, em Markdown")
    resolution: str = Field(default="answered", description="answered ou partial")
    caveats: list[str] = Field(default_factory=list, description="ressalvas feitas no texto")
    grafico: GraficoEstruturado = Field(default_factory=GraficoEstruturado)
    sugestoes: list[str] = Field(default_factory=list, description="2 a 3 continuações curtas")


def _historico(mensagens) -> str:
    if not mensagens:
        return ""
    linhas = [
        f"{'Usuário' if m.direction == 'in' else 'Você'}: {m.text}".strip()
        for m in mensagens
    ]
    return "\n\n# Conversa até aqui\n\n" + "\n".join(linhas)


# Códigos que a OpenAI devolve quando a conta ficou sem saldo ou o limite de
# gasto foi atingido. O 429 de limite de velocidade tem outro código e é
# passageiro — esse sim vale tentar de novo.
_CODIGOS_SEM_CREDITO = frozenset({"insufficient_quota", "billing_hard_limit_reached", "billing_not_active"})


def _creditos_esgotados(exc) -> bool:
    codigo = getattr(exc, "code", None)
    if codigo in _CODIGOS_SEM_CREDITO:
        return True
    corpo = getattr(exc, "body", None)
    if isinstance(corpo, dict):
        erro = corpo.get("error") if isinstance(corpo.get("error"), dict) else corpo
        if erro.get("code") in _CODIGOS_SEM_CREDITO or erro.get("type") in _CODIGOS_SEM_CREDITO:
            return True
    return "exceeded your current quota" in str(exc)


def _custo(modelo: str, entrada: int, cache: int, saida: int) -> float:
    preco = PRECOS.get(modelo)
    if preco is None:
        return 0.0
    por_entrada, por_cache, por_saida = preco
    nao_cacheada = max(entrada - cache, 0)
    return round(
        (nao_cacheada * por_entrada + cache * por_cache + saida * por_saida) / 1_000_000, 6
    )


class OpenAIProvider(AIProvider):
    def __init__(
        self,
        catalog=None,
        client=None,
        model: str = "",
        answer_model: str = "",
        effort: str = "",
        answer_effort: str = "",
    ):
        self._catalog = catalog or get_catalog()
        self._client = client
        self.model = model or os.environ.get("AI_PROVIDER_MODEL", "").strip() or MODELO_PLANO
        self.answer_model = (
            answer_model or os.environ.get("AI_ANSWER_MODEL", "").strip() or MODELO_RESPOSTA
        )
        self.effort = effort or os.environ.get("AI_PLAN_EFFORT", "").strip() or "medium"
        self.answer_effort = (
            answer_effort or os.environ.get("AI_ANSWER_EFFORT", "").strip() or "low"
        )

    @property
    def cliente(self):
        """Criado na primeira chamada: instanciar no construtor faria a
        aplicação exigir chave só para importar o módulo."""
        if self._client is None:
            from openai import OpenAI

            chave = os.environ.get("AI_PROVIDER_API_KEY", "").strip()
            if not chave:
                raise AIProviderError("AI_PROVIDER_API_KEY não está definida")
            self._client = OpenAI(api_key=chave, timeout=120.0, max_retries=0)
        return self._client

    def _chamar(self, *, modelo, instrucoes, entrada, formato, esforco, max_tokens, cache_key):
        inicio = time.monotonic()
        try:
            resposta = self.cliente.responses.parse(
                model=modelo,
                instructions=instrucoes,
                input=entrada,
                text_format=formato,
                reasoning={"effort": esforco},
                max_output_tokens=max_tokens,
                prompt_cache_key=cache_key,
            )
        except Exception as exc:  # o SDK tem uma árvore própria de erros
            if _creditos_esgotados(exc):
                raise AIQuotaExceeded(f"créditos da OpenAI esgotados: {exc}") from exc
            raise AIProviderError(f"falha na chamada ao modelo: {exc}") from exc

        latencia = int((time.monotonic() - inicio) * 1000)
        conteudo = getattr(resposta, "output_parsed", None)
        if conteudo is None:
            raise AIProviderError("o modelo não devolveu a saída estruturada esperada")

        uso = getattr(resposta, "usage", None)
        entrada_tokens = getattr(uso, "input_tokens", 0) or 0
        saida_tokens = getattr(uso, "output_tokens", 0) or 0
        cache_tokens = getattr(getattr(uso, "input_tokens_details", None), "cached_tokens", 0) or 0
        raciocinio = getattr(getattr(uso, "output_tokens_details", None), "reasoning_tokens", 0) or 0

        usage = AIUsage(
            model=modelo,
            tokens_input=entrada_tokens,
            tokens_output=saida_tokens,
            cost_estimate=_custo(modelo, entrada_tokens, cache_tokens, saida_tokens),
            latency_ms=latencia,
            request={"cache_key": cache_key, "effort": esforco, "tokens_enviados": entrada_tokens},
            response={
                "tokens_em_cache": cache_tokens,
                "tokens_de_raciocinio": raciocinio,
                "conteudo": json.loads(conteudo.model_dump_json()),
            },
        )
        return conteudo, usage

    def plan(self, request: PlanRequest) -> Plan:
        contexto = montar_contexto_do_plano(
            self._catalog,
            request.question,
            request.history,
            completo=request.full_context,
        )

        entrada = contexto.texto + _historico(request.history)
        entrada += f"\n\n# Hoje\n\n{date.today():%d/%m/%Y}"
        if request.empty_note:
            entrada += (
                "\n\n# Consulta vazia\n\n"
                + request.empty_note
                + "\n\nEscreva a consulta de verificação da seção 9.1."
            )
        if request.error_note:
            entrada += (
                "\n\n# Correção\n\nA consulta anterior não pôde ser usada: "
                f"{request.error_note}\n\nCorrija exatamente esse ponto."
            )
        entrada += f"\n\n# Pergunta do usuário\n\n{request.question}"

        conteudo, usage = self._chamar(
            modelo=self.model,
            instrucoes=load_prompt(PROMPT_VERSION),
            entrada=entrada,
            formato=PlanoEstruturado,
            esforco=self.effort,
            max_tokens=MAX_TOKENS_PLANO,
            cache_key=f"plano:{PROMPT_VERSION}:{'completo' if contexto.completo else '+'.join(contexto.secoes)}",
        )

        usage.request["secoes"] = list(contexto.secoes)
        usage.request["contexto_completo"] = contexto.completo
        intent = (conteudo.intent or "").strip()
        if intent not in _INTENCOES:
            raise AIProviderError(f"intenção desconhecida devolvida pelo modelo: {intent!r}")

        return Plan(
            intent=intent,
            sql=(conteudo.sql or "").strip(),
            reference_query_id=(conteudo.reference_query_id or "").strip(),
            clarification_question=(conteudo.clarification_question or "").strip(),
            user_message=(conteudo.user_message or "").strip(),
            reason=(conteudo.reason or "").strip(),
            excel=bool(getattr(conteudo, "excel", False)),
            usage=usage,
        )

    def answer(self, request: AnswerRequest) -> Answer:
        contexto = montar_contexto_da_resposta(self._catalog)
        linhas = [dict(zip(request.columns, linha)) for linha in request.rows]

        entrada = contexto.texto + _historico(request.history)
        # Sem a data, a redação não tem como avisar que o mês corrente ainda
        # não fechou — e uma queda aparente no último mês parece real.
        entrada += f"\n\n# Hoje\n\n{date.today():%d/%m/%Y}"
        entrada += f"\n\n# Pergunta do usuário\n\n{request.question}"
        entrada += f"\n\n# Consulta executada\n\n```sql\n{request.sql}\n```"
        if request.reference_query_id:
            entrada += f"\n\n(baseada na consulta de referência {request.reference_query_id})"
        entrada += (
            "\n\n# Resultado\n\n"
            f"Colunas: {', '.join(request.columns)}\n"
            f"Linhas ({len(linhas)}): {json.dumps(linhas, ensure_ascii=False, default=str)}"
        )
        if request.verification:
            entrada += (
                "\n\n# Consulta de verificação\n\nA consulta da pergunta não retornou "
                "nenhuma linha. O resultado acima é de uma verificação, feita para descobrir o "
                "porquê: explique ao usuário o que aconteceu (nome que não existe, pessoa que "
                "saiu antes do período, período sem carga) e ofereça o caminho que funciona. "
                "Não apresente esses números como se fossem a resposta da pergunta."
            )
        total = request.total_rows or len(linhas)
        entrada += f"\n\nTotal de linhas no resultado: {total}"
        if request.excel:
            entrada += (
                "\n\n# Planilha\n\nO usuário pediu os dados em planilha. Em uma ou duas frases, "
                "diga o que a planilha traz e quantas linhas tem, e que ele pode baixá-la pelo "
                "botão \"Baixar Excel\" logo abaixo desta resposta. Não reproduza a lista."
            )
        elif total > len(linhas):
            # Só aqui a tabela é resumida: o modelo não recebeu tudo, então
            # listar "todas" seria listar as que couberam, sem dizer isso.
            entrada += (
                f"\n\n# Lista longa\n\nVocê recebeu {len(linhas)} das {total} linhas. Mostre as "
                "que recebeu, diga quantas ficaram de fora e aponte o botão \"Baixar Excel\" "
                "abaixo da resposta, que traz a lista completa."
            )
        else:
            entrada += (
                "\n\n# Lista\n\nVocê recebeu o resultado inteiro: a tabela leva todas as "
                f"{total} linhas, sem cortar."
            )
        if request.truncated:
            entrada += "\n\nO resultado foi cortado no limite de linhas: não é o total. A planilha traz a lista completa."
        if request.revision_note:
            entrada += (
                "\n\n# Revisão\n\nA sua resposta anterior citou número sem suporte no "
                f"resultado: {request.revision_note}\n\nReescreva sem esse número."
            )

        conteudo, usage = self._chamar(
            modelo=self.answer_model,
            instrucoes=load_prompt(ANSWER_PROMPT_VERSION),
            entrada=entrada,
            formato=RespostaEstruturada,
            esforco=self.answer_effort,
            max_tokens=MAX_TOKENS_RESPOSTA,
            cache_key=f"resposta:{ANSWER_PROMPT_VERSION}",
        )

        texto = (conteudo.reply or "").strip()
        if not texto:
            raise AIProviderError("o modelo devolveu uma resposta vazia")

        grafico = getattr(conteudo, "grafico", None)
        return Answer(
            reply=texto,
            resolution=(conteudo.resolution or "answered").strip(),
            caveats=tuple(conteudo.caveats or ()),
            chart=grafico.model_dump() if grafico is not None else {},
            followups=tuple(getattr(conteudo, "sugestoes", ()) or ()),
            usage=usage,
        )
