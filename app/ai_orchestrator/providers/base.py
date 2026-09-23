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


class AIOutputTruncated(AIProviderError):
    """A saída passou do limite de tokens e chegou cortada no meio — o JSON
    nem fecha. Tentar de novo dá o mesmo corte e paga de novo: em produção
    (2026-09-21) "quais CDs estão em ruptura?" custou três tentativas iguais
    cada vez. Quem chama cai para o que dá sem o modelo (a tabela crua)."""


@dataclass(frozen=True)
class HistoryMessage:
    direction: str  # "in" (pergunta) | "out" (resposta enviada)
    text: str
    # Nas últimas respostas: a consulta e o gráfico que a sustentaram. Sem
    # isto o planejador só via o texto, e "faça um gráfico com esses dados"
    # ou "qual MAT você usou?" não tinham de onde partir (2026-09-23).
    fonte: str = ""


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
    # Resumo da planilha que o usuário anexou (ADR-0024): cabeçalhos, tipos e
    # amostra, nunca o conteúdo. Some junto a instrução de propor o
    # casamento entre a coluna da planilha e a coluna do resultado.
    planilha: str = ""
    # Preenchido só na correção única (ADR-0014): o motivo pelo qual a
    # consulta anterior foi recusada pelo validador ou pelo banco.
    error_note: str = ""
    # Preenchido quando a consulta rodou e não voltou nenhuma linha: o plano
    # seguinte é uma consulta de verificação, não a mesma pergunta de novo.
    empty_note: str = ""
    # Contexto recortado por tema é o normal (ADR-0015); esta bandeira pede
    # o documento inteiro, quando o recorte se mostrou insuficiente.
    full_context: bool = False
    # Força o modelo principal: é a segunda tentativa, depois de o modelo
    # barato ter visto que a conversa curta era, na verdade, pergunta de dado.
    sem_atalho: bool = False
    # Investigação (ADR-0025): o que as consultas das rodadas anteriores
    # mostraram, em texto compacto, e em que rodada estamos. Com achados, o
    # planejador decide se aprofunda (novas hipóteses) ou se já dá para
    # concluir.
    achados: str = ""
    rodada: int = 1


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
        # Pergunta de porquê (ADR-0025): várias consultas, uma por hipótese,
        # em rodadas — "a queda foi geral ou concentrada?", "algum
        # concorrente ganhou share?". O planejador escreve as hipóteses.
        INVESTIGATE = "investigate"
        # Só depois de achados: o que foi consultado já explica, hora de
        # escrever a análise.
        CONCLUDE = "conclude"

    intent: str
    sql: str = ""
    reference_query_id: str = ""
    clarification_question: str = ""
    reason: str = ""
    # A pergunta como o planejador a entendeu, reescrita inteira — num
    # seguimento, junta o que já estava na conversa com o que mudou. Sem
    # este campo, "considere Extras, MP, SS e Voucher também" reaproveitou a
    # consulta anterior quase igual e devolveu o mesmo número (conversa 15,
    # 2026-09-23): nada obrigava o modelo a dizer o que tinha mudado.
    entendimento: str = ""
    # A parte do pedido que a consulta NÃO atende, e por quê (fonte sem
    # carga, recorte que não existe, gráfico que não há). Vai para a redação,
    # que abre a resposta dizendo isso em vez de fingir que atendeu.
    pedido_nao_atendido: str = ""
    # Texto ao usuário em "não sei" e "fora de escopo": o documento de
    # referência pede orientações específicas (forecast vai para outro app,
    # meta ainda não está disponível) que um texto fixo não cobre.
    user_message: str = ""
    # O usuário pediu os dados em planilha ("quero em Excel"): a resposta
    # fica curta e aponta para o download, em vez de despejar a lista.
    excel: bool = False
    # Como preencher a planilha anexada (ADR-0024): a coluna-chave dos dois
    # lados e, para cada coluna a preencher, de qual coluna do resultado vem
    # o valor. Só nomes — o modelo nunca manda valor, porque valor vem do
    # banco. Formato: {"coluna_chave", "chave_no_resultado",
    # "colunas": [{"coluna_destino", "valor_no_resultado"}, ...]}.
    preenchimento: dict = field(default_factory=dict)
    # Em `investigate`: as hipóteses desta rodada, cada uma com a consulta
    # que a testa — ({"hipotese", "sql", "reference_query_id"}, ...).
    investigacao: tuple = ()
    # Projeção de Sell Out ou Sell In da Ease: o sistema acrescenta à resposta
    # a orientação de conferir o dashboard de Forecast de Reposição. Fica
    # fora do texto do modelo de propósito — assim ela nunca depende de ele
    # lembrar, e não gasta token.
    ressalva_forecast: bool = False
    # Em `investigate`: estas consultas já fecham a investigação. Poupa a
    # chamada seguinte ao planejador, que em quase toda investigação só
    # servia para ele dizer "pode concluir" — ~US$ 0,05 por pergunta.
    rodada_final: bool = False
    usage: AIUsage = field(default_factory=AIUsage)
    # Chamadas de planejamento descartadas antes desta: o modelo barato que
    # tentou a conversa curta e viu que era pergunta de dado. Pagas do mesmo
    # jeito — a auditoria registra cada uma.
    tentativas: tuple = ()


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
    # Lista longa (ADR-0025): a tabela é desenhada pela tela, e o modelo
    # recebeu só uma amostra das linhas. Ele escreve o texto e aponta a
    # tabela em `blocos`, sem copiar linha nenhuma.
    tabela_em_bloco: bool = False
    # Investigação (ADR-0025): o resultado de cada hipótese consultada, na
    # ordem — ({"hipotese", "sql", "columns", "rows", "total_rows"}, ...).
    # Com isto preenchido, `sql`, `columns` e `rows` ficam vazios e a
    # redação escreve a análise que cruza as consultas.
    consultas: tuple = ()
    # O que o planejador entendeu do pedido e o que a consulta deixou de
    # fora (ver `Plan`). Sem isto a redação só via a pergunta solta e o
    # resultado, e não tinha como perceber que o seguimento pediu uma
    # mudança que não aconteceu.
    entendimento: str = ""
    pedido_nao_atendido: str = ""


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
    # Resposta em blocos, na ordem de leitura (ADR-0025): texto, tabela,
    # texto, gráfico — quando isso lê melhor que texto + tabela. Tabela e
    # gráfico apontam uma consulta pelo índice; quem desenha é a tela, com
    # os números do banco. Vazio: vale `reply` com `chart`, como antes.
    # ({"tipo": "texto", "texto"} | {"tipo": "tabela", "consulta", "colunas"}
    #  | {"tipo": "grafico", "consulta", "grafico"}, ...)
    blocos: tuple = ()
    usage: AIUsage = field(default_factory=AIUsage)


@dataclass(frozen=True)
class ImageRequest:
    """Uma imagem para ler e comentar (ADR-0024).

    `imagem_png` já vem validada e reduzida por `attachments/imagem.py`: o
    provedor não decide dimensão, porque dimensão é custo.
    """

    question: str
    imagem_png: bytes
    history: tuple = ()


@dataclass(frozen=True)
class ImageReading:
    """O que o modelo leu na imagem, separado do que ele concluiu.

    A separação é o que permite rotular a resposta: nada aqui passou pelo
    banco, então nada aqui pode ser apresentado como dado da Ease Labs
    (ADR-0010, ADR-0024).
    """

    leitura: str
    resposta: str
    # Instruções que vinham escritas dentro da imagem, quando houver: texto
    # em imagem é dado, nunca ordem (ADR-0021). Fica registrado.
    instrucoes_ignoradas: str = ""
    # O pedido só se resolve com dado da empresa ("preencha esta tabela",
    # "isso bate com o nosso sell-out?"). Aí a imagem deixa de ser a
    # resposta e vira o ponto de partida de uma consulta ao banco.
    precisa_do_banco: bool = False
    # A tabela do print, transcrita: cabeçalhos e linhas como estão lá. Vira
    # uma planilha em memória e segue o caminho do preenchimento.
    tabela_colunas: tuple = ()
    tabela_linhas: tuple = ()
    # Pergunta autossuficiente para o banco, quando não há tabela a
    # preencher: o que a pessoa quer saber, com os nomes lidos na imagem.
    pergunta_ao_banco: str = ""
    usage: AIUsage = field(default_factory=AIUsage)


class AIProvider(ABC):
    @abstractmethod
    def plan(self, request: PlanRequest) -> Plan:
        """Decide o que fazer com a pergunta e escreve a consulta."""

    @abstractmethod
    def answer(self, request: AnswerRequest) -> Answer:
        """Redige a resposta a partir do resultado da consulta."""

    def read_image(self, request: ImageRequest) -> ImageReading:
        """Lê a imagem anexada e comenta o que viu.

        Concreto, e não abstrato, de propósito: os dublês dos testes e
        qualquer provedor futuro continuam válidos sem saber ler imagem — o
        orquestrador trata esta falha como "não consigo ler imagem agora".
        """
        raise AIProviderError("este provedor não lê imagem")
