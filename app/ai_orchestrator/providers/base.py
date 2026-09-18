"""Interface abstrata do provedor de IA (ADR-0005).

São duas chamadas por resposta, e elas são diferentes o bastante para virar
dois métodos: `plan` escreve a consulta a partir da pergunta e das
referências; `answer` redige o texto a partir do resultado que voltou do
banco. O orquestrador não conhece nada além deste contrato.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class AIProviderError(Exception):
    """Falha do provedor (timeout, indisponibilidade, resposta fora do
    contrato). Implementações traduzem o erro nativo do SDK para esta
    exceção; o orquestrador só conhece ela."""


class AIQuotaExceeded(AIProviderError):
    """Os créditos da conta no provedor acabaram (ou a cobrança foi
    bloqueada). Diferente de uma falha passageira: tentar de novo não
    resolve — só alguém recarregando a conta. Por isso não passa pelo retry
    e vira uma mensagem própria ao usuário."""


@dataclass(frozen=True)
class HistoryMessage:
    direction: str  # "in" (pergunta) | "out" (resposta enviada)
    text: str


@dataclass(frozen=True)
class AIUsage:
    """Custo e latência de uma chamada, para a auditoria (FR-15)."""

    model: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    cost_estimate: float = 0.0
    latency_ms: int = 0
    request: dict = field(default_factory=dict)
    response: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PlanRequest:
    question: str
    history: tuple = ()
    # Preenchido só na correção única (ADR-0014): o motivo pelo qual a
    # consulta anterior foi recusada pelo validador ou pelo banco.
    error_note: str = ""
    # Preenchido quando a consulta rodou e não voltou nenhuma linha: o plano
    # seguinte é uma consulta de verificação, não a mesma pergunta de novo.
    empty_note: str = ""
    # Contexto recortado por tema é o normal (ADR-0015); esta bandeira pede
    # o documento inteiro, quando o recorte se mostrou insuficiente.
    full_context: bool = False


@dataclass(frozen=True)
class Plan:
    class Intent:
        ANSWER_WITH_DATA = "answer_with_data"
        CLARIFY = "clarify"
        UNKNOWN = "unknown"
        OUT_OF_SCOPE = "out_of_scope"
        # Resposta direta, sem consultar o banco: cumprimento, "quem é você",
        # conceito do negócio ou interpretação do que já está na conversa.
        CONVERSATION = "conversation"

    intent: str
    sql: str = ""
    reference_query_id: str = ""
    clarification_question: str = ""
    reason: str = ""
    # Texto ao usuário em "não sei" e "fora de escopo": o documento de
    # referência pede orientações específicas (forecast vai para outro app,
    # meta ainda não está disponível) que um texto fixo não cobre.
    user_message: str = ""
    # O usuário pediu os dados em planilha ("quero em Excel"): a resposta
    # fica curta e aponta para o download, em vez de despejar a lista.
    excel: bool = False
    usage: AIUsage = field(default_factory=AIUsage)


@dataclass(frozen=True)
class AnswerRequest:
    question: str
    sql: str
    columns: tuple
    rows: tuple
    truncated: bool
    reference_query_id: str = ""
    history: tuple = ()
    # Preenchido só na reescrita: o número que a resposta citou sem suporte
    # no resultado (ADR-0010).
    revision_note: str = ""
    # Quantas linhas a consulta devolveu (a IA lê no máximo 50) e se o
    # usuário pediu planilha: é o que decide mostrar a lista ou apontar para
    # o botão "Baixar Excel".
    total_rows: int = 0
    excel: bool = False
    # O resultado abaixo é de uma consulta de verificação (a da pergunta
    # voltou vazia): a resposta explica o que aconteceu, não o número.
    verification: bool = False


@dataclass(frozen=True)
class Answer:
    reply: str
    resolution: str = "answered"
    caveats: tuple = ()
    # Sugestão de gráfico (ADR-0020): só o tipo e quais colunas usar. Quem
    # desenha é o navegador, com os números da consulta — nunca a IA.
    chart: dict = field(default_factory=dict)
    # Continuações prováveis da investigação, para a tela oferecer em um
    # clique. Texto de pergunta, não de resposta: não passa pela ancoragem.
    followups: tuple = ()
    usage: AIUsage = field(default_factory=AIUsage)


class AIProvider(ABC):
    @abstractmethod
    def plan(self, request: PlanRequest) -> Plan:
        """Decide o que fazer com a pergunta e escreve a consulta."""

    @abstractmethod
    def answer(self, request: AnswerRequest) -> Answer:
        """Redige a resposta a partir do resultado da consulta."""
