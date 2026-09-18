"""Orquestrador: da pergunta à resposta (SPEC.md seção 5).

A ordem das etapas é a regra do produto, então ela fica visível aqui e a
lógica de cada uma mora no seu próprio módulo:

    idempotência → regras determinísticas → planejamento (SQL) → validação
    → execução → redação → ancoragem numérica → registro

Duas correções únicas existem no caminho, e as duas são deliberadas: se a
consulta é recusada ou falha, a IA reescreve uma vez com o erro (ADR-0014);
se a resposta cita número sem suporte, ela reescreve uma vez com o motivo
(ADR-0010). Na segunda falha o sistema para de tentar e entrega algo
honesto, em vez de insistir.
"""

import logging
import os
import re
from dataclasses import dataclass, field

from ai_orchestrator import budget, canned
from ai_orchestrator.context import PEDIDO_DE_SECAO
from ai_orchestrator.grounding import check_grounding
from ai_orchestrator.models import AICall, AIReply, CatalogGap
from ai_orchestrator.providers.base import (
    AIProviderError,
    AIQuotaExceeded,
    AnswerRequest,
    HistoryMessage,
    Plan,
    PlanRequest,
)
from ai_orchestrator.providers.fake import FakeAIProvider
from ai_orchestrator.prompts import PROMPT_VERSION
from ai_orchestrator.rules import apply_rules
from catalog.loader import get_catalog
from datasource.executors.base import QueryExecutionError, QueryObjectMissing, QueryTimeout
from datasource.executors.fake import FakeQueryExecutor
from datasource.models import QueryRun
from datasource.sql_guard import validate_sql
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from messaging.services import deliver_reply

logger = logging.getLogger(__name__)

DEFAULT_MAX_HISTORY_MESSAGES = 10
MAX_LINHAS_NA_TABELA = 20


def _max_history_messages() -> int:
    """Quantas mensagens anteriores entram no contexto. Configurável por
    AI_HISTORY_MAX_MESSAGES; mais contexto ajuda em perguntas de seguimento e
    custa tokens em toda chamada."""
    bruto = os.environ.get("AI_HISTORY_MAX_MESSAGES", "").strip()
    try:
        valor = int(bruto)
    except ValueError:
        return DEFAULT_MAX_HISTORY_MESSAGES
    return valor if valor > 0 else DEFAULT_MAX_HISTORY_MESSAGES


def _historico(message: Message) -> tuple:
    """Mensagens anteriores da conversa, em ordem, sem a atual.

    O escopo é a conversa (e não o usuário, como na referência): aqui cada
    thread é um assunto, e misturar contextos faria "e em julho?" seguir a
    pergunta errada."""
    anteriores = (
        Message.objects.filter(conversation=message.conversation)
        .exclude(pk=message.pk)
        .filter(id__lt=message.id)
        .order_by("-id")[: _max_history_messages()]
    )
    return tuple(
        HistoryMessage(direction=m.direction, text=m.content) for m in reversed(list(anteriores))
    )


@dataclass
class _Decisao:
    decision: str
    reply: str
    rule: str = ""
    raw: dict = field(default_factory=dict)
    message_status: str = Message.Status.PROCESSED
    gap_reason: str = ""


@dataclass
class _Auditoria:
    """Junta o que aconteceu para gravar de uma vez no fim.

    As linhas de AICall e QueryRun dependem do AIReply, que só existe quando
    a decisão está tomada — e gravar no fim mantém o registro coerente mesmo
    quando o caminho é interrompido por uma falha."""

    chamadas: list = field(default_factory=list)
    consultas: list = field(default_factory=list)

    def chamada(self, stage: str, usage) -> None:
        self.chamadas.append((stage, usage))

    def consulta(self, **campos) -> None:
        self.consultas.append(campos)

    @property
    def totais(self) -> dict:
        return {
            "tokens_input": sum(u.tokens_input for _, u in self.chamadas),
            "tokens_output": sum(u.tokens_output for _, u in self.chamadas),
            "cost_estimate": sum(u.cost_estimate for _, u in self.chamadas),
            "latency_ms": sum(u.latency_ms for _, u in self.chamadas),
        }

    @property
    def modelo(self) -> str:
        return self.chamadas[-1][1].model if self.chamadas else ""


def _tabela(resultado) -> str:
    """Resultado em texto, sem narrativa nenhuma.

    É a saída de segurança quando a redação insiste em citar número sem
    suporte: o usuário continua recebendo o dado, só que sem frase em volta
    (ADR-0010)."""
    cabecalho = " | ".join(resultado.columns)
    linhas = [
        " | ".join("" if v is None else str(v) for v in linha)
        for linha in resultado.rows[:MAX_LINHAS_NA_TABELA]
    ]
    return "\n".join([cabecalho, *linhas])


def _nota_de_truncamento(resultado, max_rows: int) -> str:
    if not resultado.truncated:
        return ""
    return (
        f"\n\n(Resultado cortado no limite de {max_rows} linhas: o que você vê "
        "é uma parte, não o total.)"
    )


def _executar_com_correcao(plano, message, provider, executor, catalog, auditoria, historico):
    """Valida e executa, com uma correção se der errado (ADR-0014).

    Devolve (plano, resultado, erro, inexistente). Resultado None significa
    que a consulta não saiu; `inexistente` diz que foi porque o banco não tem
    a tabela ou o schema — caso em que não há correção: o documento de
    referência manda não trocar por outra tabela parecida.
    """
    tentativa = 1
    while True:
        guard = validate_sql(plano.sql, catalog, max_rows=catalog.max_rows)

        if not guard.approved:
            auditoria.consulta(
                attempt=tentativa,
                sql=plano.sql,
                reference_query_id=plano.reference_query_id,
                guard_result=QueryRun.GuardResult.REJECTED,
                guard_reason=guard.reason,
                status=QueryRun.Status.NOT_EXECUTED,
            )
            erro = guard.reason
        else:
            # A tela mostra "consultando os dados" só a partir daqui: antes
            # disso a IA ainda pode decidir responder sem consulta.
            Message.objects.filter(pk=message.pk).update(status=Message.Status.PROCESSING)
            try:
                resultado = executor.run(guard.sql, max_rows=catalog.max_rows)
            except QueryExecutionError as exc:
                auditoria.consulta(
                    attempt=tentativa,
                    sql=plano.sql,
                    reference_query_id=plano.reference_query_id,
                    guard_result=QueryRun.GuardResult.APPROVED,
                    status=(
                        QueryRun.Status.TIMEOUT
                        if isinstance(exc, QueryTimeout)
                        else QueryRun.Status.ERROR
                    ),
                    error=str(exc),
                )
                erro = str(exc)
                if isinstance(exc, QueryObjectMissing):
                    return plano, None, erro, True
            else:
                auditoria.consulta(
                    attempt=tentativa,
                    sql=plano.sql,
                    reference_query_id=plano.reference_query_id,
                    guard_result=QueryRun.GuardResult.APPROVED,
                    status=QueryRun.Status.SUCCESS,
                    row_count=resultado.row_count,
                    truncated=resultado.truncated,
                    duration_ms=resultado.duration_ms,
                    result_sample={
                        "columns": list(resultado.columns),
                        "rows": [list(linha) for linha in resultado.rows[:5]],
                    },
                )
                return plano, resultado, "", False

        if tentativa == 2:
            return plano, None, erro, False

        tentativa += 1
        plano = provider.plan(
            PlanRequest(question=message.content, history=historico, error_note=erro)
        )
        auditoria.chamada(AICall.Stage.FIX, plano.usage)
        if plano.intent != Plan.Intent.ANSWER_WITH_DATA or not plano.sql:
            # A IA desistiu na correção: não force uma terceira tentativa.
            return plano, None, erro, False


NOTA_DE_VAZIO = (
    "A consulta rodou sem erro e não retornou nenhuma linha. Descubra o motivo: "
    "o nome pode não ter casado com o cadastro, a pessoa pode não estar ativa no "
    "período, ou o período pode não ter carga."
)


def _verificar_o_vazio(message, provider, executor, catalog, auditoria, historico):
    """Resultado vazio quase nunca é "não houve" (regra do documento).

    Antes de dizer que não há dado, uma segunda consulta — cadastral, sem o
    filtro que pode ter zerado tudo — procura o motivo: o nome existe? a
    pessoa estava ativa? o mês tem carga? Custa um plano a mais, e só quando
    a consulta volta vazia, o que é raro. Devolve (resultado, plano); o
    resultado é None quando a verificação também não esclareceu nada."""
    plano = provider.plan(
        PlanRequest(question=message.content, history=historico, empty_note=NOTA_DE_VAZIO)
    )
    auditoria.chamada(AICall.Stage.FIX, plano.usage)
    if plano.intent != Plan.Intent.ANSWER_WITH_DATA or not plano.sql:
        return None, plano

    tentativa = len(auditoria.consultas) + 1
    guard = validate_sql(plano.sql, catalog, max_rows=catalog.max_rows)
    if not guard.approved:
        auditoria.consulta(
            attempt=tentativa,
            sql=plano.sql,
            reference_query_id=plano.reference_query_id,
            guard_result=QueryRun.GuardResult.REJECTED,
            guard_reason=guard.reason,
            status=QueryRun.Status.NOT_EXECUTED,
        )
        return None, plano

    try:
        resultado = executor.run(guard.sql, max_rows=catalog.max_rows)
    except QueryExecutionError as exc:
        # A verificação é um extra: se ela falhar, o usuário recebe o aviso
        # de resultado vazio, não um erro que ele não pediu.
        auditoria.consulta(
            attempt=tentativa,
            sql=plano.sql,
            reference_query_id=plano.reference_query_id,
            guard_result=QueryRun.GuardResult.APPROVED,
            status=(QueryRun.Status.TIMEOUT if isinstance(exc, QueryTimeout) else QueryRun.Status.ERROR),
            error=str(exc),
        )
        return None, plano

    auditoria.consulta(
        attempt=tentativa,
        sql=plano.sql,
        reference_query_id=plano.reference_query_id,
        guard_result=QueryRun.GuardResult.APPROVED,
        status=QueryRun.Status.SUCCESS,
        row_count=resultado.row_count,
        truncated=resultado.truncated,
        duration_ms=resultado.duration_ms,
        result_sample={
            "columns": list(resultado.columns),
            "rows": [list(linha) for linha in resultado.rows[:5]],
        },
    )
    return (resultado if resultado.row_count else None), plano


TIPOS_DE_GRAFICO = frozenset({"linha", "barras", "barras_horizontais"})
MAX_SERIES = 3


def _grafico(sugestao, resultado, message, plano) -> dict | None:
    """Confere a sugestão de gráfico contra o resultado de verdade (ADR-0020).

    A IA só escolhe o tipo e as colunas; o desenho usa os números da
    consulta. Coluna inexistente, série que não é número ou resultado de uma
    linha só não viram gráfico — melhor nenhum gráfico do que um errado."""
    if not sugestao or sugestao.get("tipo") not in TIPOS_DE_GRAFICO or resultado.row_count < 2:
        return None
    colunas = list(resultado.columns)
    x = sugestao.get("x")
    if x not in colunas:
        return None

    def numerica(nome):
        i = colunas.index(nome)
        valores = [linha[i] for linha in resultado.rows if linha[i] is not None]
        return bool(valores) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in valores
        )

    series = [s for s in dict.fromkeys(sugestao.get("series") or []) if s in colunas and s != x and numerica(s)]
    if not series:
        return None

    titulo = " ".join(str(sugestao.get("titulo") or "").split())[:80]
    if titulo and not check_grounding(titulo, resultado.columns, resultado.rows, message.content, plano.sql).ok:
        titulo = ""
    return {"tipo": sugestao["tipo"], "x": x, "series": series[:MAX_SERIES], "titulo": titulo}


def _guardar_dados_do_grafico(auditoria, resultado) -> None:
    """A tela desenha o gráfico com o resultado inteiro (até o limite de
    linhas), não com a amostra de 5 que a auditoria guarda por padrão."""
    for consulta in reversed(auditoria.consultas):
        if consulta.get("status") == QueryRun.Status.SUCCESS:
            consulta["result_sample"] = {
                "columns": list(resultado.columns),
                "rows": [list(linha) for linha in resultado.rows],
            }
            return


def _redigir(plano, resultado, message, provider, catalog, auditoria, historico, verificacao=False):
    """Redige a resposta e confere a ancoragem numérica (ADR-0010)."""
    pedido = AnswerRequest(
        question=message.content,
        sql=plano.sql,
        columns=resultado.columns,
        rows=resultado.rows[: catalog.rows_to_model],
        truncated=resultado.truncated,
        reference_query_id=plano.reference_query_id,
        history=historico,
        total_rows=resultado.row_count,
        excel=plano.excel,
        verification=verificacao,
    )
    resposta = provider.answer(pedido)
    auditoria.chamada(AICall.Stage.ANSWER, resposta.usage)

    extras = {"excel": plano.excel}
    # Verificação não vira gráfico: o resultado é cadastral, e desenhá-lo
    # daria ao diagnóstico a aparência da resposta que não existe.
    grafico = None if (plano.excel or verificacao) else _grafico(resposta.chart, resultado, message, plano)
    if grafico:
        extras["grafico"] = grafico
        _guardar_dados_do_grafico(auditoria, resultado)

    conferencia = check_grounding(
        resposta.reply, resultado.columns, resultado.rows, message.content, plano.sql,
        row_count=resultado.row_count,
    )
    if conferencia.ok:
        return resposta.reply, {"caveats": list(resposta.caveats), **extras}

    rascunhos = [resposta.reply]
    motivos = [conferencia.reason]

    reescrita = provider.answer(
        AnswerRequest(**{**pedido.__dict__, "revision_note": conferencia.reason})
    )
    auditoria.chamada(AICall.Stage.REWRITE, reescrita.usage)

    segunda = check_grounding(
        reescrita.reply, resultado.columns, resultado.rows, message.content, plano.sql,
        row_count=resultado.row_count,
    )
    if segunda.ok:
        return reescrita.reply, {
            "caveats": list(reescrita.caveats),
            "rascunho_reprovado": rascunhos,
            "motivos_ancoragem": motivos,
            **extras,
        }

    rascunhos.append(reescrita.reply)
    motivos.append(segunda.reason)
    logger.warning("Resposta reprovada duas vezes na ancoragem; enviando a tabela crua")
    return _tabela(resultado), {
        "rule": "resposta_sem_narrativa",
        "rascunho_reprovado": rascunhos,
        "motivos_ancoragem": motivos,
        **extras,
    }


def _conversa(plano, message, historico) -> _Decisao:
    """Resposta sem consulta (ADR-0019): cumprimento, o que o assistente
    faz, conceito do negócio ou leitura do que já apareceu na conversa.

    Continua valendo "número só com fonte" (ADR-0010): a resposta pode citar
    número que está na pergunta ou em mensagens anteriores desta conversa —
    que vieram de consulta —, nunca um número novo. Se citar, sai o texto de
    reserva pedindo período e recorte para consultar de verdade."""
    texto = (plano.user_message or "").strip()
    if _vazou_instrucoes(texto):
        logger.warning("Resposta de conversa repetiu o prompt; usando o texto de recusa")
        return _Decisao(
            decision=AIReply.Decision.OUT_OF_SCOPE,
            reply=canned.TENTATIVA_DE_INJECAO,
            rule="tentativa_de_injecao",
            raw={"reason": plano.reason, "rascunho": texto},
        )
    contexto = "\n".join([message.content, *(m.text for m in historico)])
    if texto and check_grounding(texto, (), (), contexto, "").ok:
        return _Decisao(
            decision=AIReply.Decision.CONVERSATION,
            reply=texto,
            raw={"reason": plano.reason},
        )
    logger.warning("Resposta de conversa sem texto ou com número sem fonte; usando o texto de reserva")
    return _Decisao(
        decision=AIReply.Decision.CONVERSATION,
        reply=canned.CONVERSA_COM_NUMERO,
        rule="conversa_com_numero_sem_fonte",
        raw={"reason": plano.reason, "rascunho": texto},
    )


# Pedaços que só existem dentro do prompt do planejador: se aparecem no
# texto ao usuário, a mensagem conseguiu fazer o modelo contar como ele
# funciona por dentro (ADR-0021). Vale a rede porque o custo é zero e a
# alternativa é confiar em o modelo nunca escorregar.
_MARCAS_DO_PROMPT = re.compile(
    r"answer_with_data|out_of_scope|reference_query_id|clarification_question|"
    r"\buser_message\b|system\s*prompt|prompt\s+do\s+sistema",
    re.I,
)


def _vazou_instrucoes(texto: str) -> bool:
    return bool(_MARCAS_DO_PROMPT.search(texto or ""))


def _pediu_o_documento_inteiro(plano) -> bool:
    return plano.intent == Plan.Intent.UNKNOWN and (plano.reason or "").strip().upper().startswith(
        PEDIDO_DE_SECAO
    )


def _mensagem_sem_dado(plano, message, padrao: str) -> str:
    """Texto da IA para "não sei" ou "fora de escopo", se ele não trouxer
    número.

    Nessas decisões nenhuma consulta rodou, então qualquer número no texto
    seria inventado (ADR-0010): nesse caso, e quando a IA não escreveu nada,
    vale o texto fixo."""
    texto = (plano.user_message or "").strip()
    if not texto:
        return padrao
    if _vazou_instrucoes(texto):
        logger.warning("Mensagem sem dado repetiu o prompt; usando o texto padrão")
        return canned.TENTATIVA_DE_INJECAO
    if not check_grounding(texto, (), (), message.content, "").ok:
        logger.warning("Mensagem sem dado citou número; usando o texto padrão")
        return padrao
    return texto


def _processar(message, provider, executor, catalog, auditoria) -> _Decisao:
    regra = apply_rules(message.content, catalog)
    if regra is not None:
        return _Decisao(
            decision=regra.decision, reply=regra.reply, rule=regra.rule
        )

    if budget.excedido():
        # Antes de qualquer chamada paga: o teto existe para o custo não
        # depender de estimativa (O-14).
        logger.warning("Teto de gasto do mês atingido; a pergunta não foi para o modelo")
        return _Decisao(
            decision=AIReply.Decision.FAILED,
            reply=canned.LIMITE_DE_CUSTO,
            rule="teto_de_custo_do_mes",
            message_status=Message.Status.FAILED,
        )

    historico = _historico(message)
    plano = provider.plan(PlanRequest(question=message.content, history=historico))
    auditoria.chamada(AICall.Stage.PLAN, plano.usage)

    if _pediu_o_documento_inteiro(plano):
        # O contexto vai recortado por tema (ADR-0015). Quando o recorte não
        # basta, a IA avisa em vez de inventar a regra que faltou.
        logger.info("A IA pediu o documento inteiro: %s", plano.reason)
        plano = provider.plan(
            PlanRequest(question=message.content, history=historico, full_context=True)
        )
        auditoria.chamada(AICall.Stage.FIX, plano.usage)

    if plano.intent == Plan.Intent.CONVERSATION:
        return _conversa(plano, message, historico)

    if plano.intent == Plan.Intent.CLARIFY:
        return _Decisao(
            decision=AIReply.Decision.CLARIFY,
            reply=plano.clarification_question or canned.MENSAGEM_SEM_PERGUNTA,
            raw={"reason": plano.reason},
        )

    if plano.intent == Plan.Intent.OUT_OF_SCOPE:
        return _Decisao(
            decision=AIReply.Decision.OUT_OF_SCOPE,
            # O texto de reserva é o genérico: quando a IA decide fora de
            # escopo, quase nunca é pedido de escrita (esse a regra pega
            # antes), e sim assunto que não é o do assistente.
            reply=_mensagem_sem_dado(plano, message, canned.FORA_DE_ESCOPO),
            raw={"reason": plano.reason},
        )

    if plano.intent == Plan.Intent.UNKNOWN or not plano.sql:
        return _Decisao(
            decision=AIReply.Decision.UNKNOWN,
            reply=_mensagem_sem_dado(plano, message, canned.NAO_SEI),
            raw={"reason": plano.reason},
            gap_reason=plano.reason or "a IA não localizou o dado nas tabelas conhecidas",
        )

    plano, resultado, erro, inexistente = _executar_com_correcao(
        plano, message, provider, executor, catalog, auditoria, historico
    )

    if inexistente:
        return _Decisao(
            decision=AIReply.Decision.UNKNOWN,
            reply=canned.DADO_INDISPONIVEL,
            rule="objeto_inexistente_no_banco",
            raw={"erro": erro, "reference_query_id": plano.reference_query_id},
            gap_reason=f"a consulta usa algo que não existe no banco: {erro}",
        )

    if resultado is None:
        if plano.intent == Plan.Intent.UNKNOWN:
            return _Decisao(
                decision=AIReply.Decision.UNKNOWN,
                reply=_mensagem_sem_dado(plano, message, canned.NAO_SEI),
                raw={"reason": plano.reason, "erro": erro},
                gap_reason=plano.reason or erro,
            )
        return _Decisao(
            decision=AIReply.Decision.FAILED,
            reply=canned.CONSULTA_NAO_APROVADA.format(motivo=erro),
            rule="consulta_falhou_duas_vezes",
            raw={"erro": erro},
            message_status=Message.Status.FAILED,
            gap_reason=f"consulta falhou duas vezes: {erro}",
        )

    if resultado.row_count == 0:
        # "Nenhuma linha" não é "não houve venda": na maioria das vezes o nome
        # não casou com o cadastro ou o período não tem dado. Uma consulta de
        # verificação procura o motivo antes de responder.
        diagnostico, plano_da_verificacao = _verificar_o_vazio(
            message, provider, executor, catalog, auditoria, historico
        )
        if diagnostico is None:
            return _Decisao(
                decision=AIReply.Decision.EMPTY_RESULT,
                reply=_mensagem_sem_dado(plano_da_verificacao, message, canned.RESULTADO_VAZIO),
                rule="resultado_vazio_sem_diagnostico",
                raw={"reference_query_id": plano.reference_query_id},
            )
        texto, raw = _redigir(
            plano_da_verificacao, diagnostico, message, provider, catalog, auditoria, historico,
            verificacao=True,
        )
        return _Decisao(
            decision=AIReply.Decision.EMPTY_RESULT,
            reply=texto,
            rule=raw.pop("rule", "") or "resultado_vazio_verificado",
            raw={**raw, "reference_query_id": plano.reference_query_id},
        )

    texto, raw = _redigir(plano, resultado, message, provider, catalog, auditoria, historico)
    return _Decisao(
        decision=AIReply.Decision.ANSWERED,
        reply=texto + _nota_de_truncamento(resultado, catalog.max_rows),
        rule=raw.pop("rule", ""),
        raw={**raw, "reference_query_id": plano.reference_query_id},
    )


def _gravar(message, catalog, auditoria, decisao) -> AIReply:
    totais = auditoria.totais
    reply = AIReply.objects.create(
        message=message,
        decision=decisao.decision,
        rule=decisao.rule,
        reply_text=decisao.reply,
        prompt_version=PROMPT_VERSION,
        catalog_hash=catalog.hash,
        raw_response=decisao.raw,
        **totais,
    )

    for stage, usage in auditoria.chamadas:
        AICall.objects.create(
            ai_reply=reply,
            stage=stage,
            model=usage.model,
            tokens_input=usage.tokens_input,
            tokens_output=usage.tokens_output,
            cost_estimate=usage.cost_estimate,
            latency_ms=usage.latency_ms,
            request=usage.request,
            response=usage.response,
        )

    for campos in auditoria.consultas:
        QueryRun.objects.create(ai_reply=reply, **campos)

    if decisao.gap_reason:
        CatalogGap.objects.create(
            message=message, question=message.content, reason=decisao.gap_reason
        )

    message.status = decisao.message_status
    message.save(update_fields=["status"])
    return reply


def handle_message(message, channel=None, provider=None, executor=None, catalog=None) -> AIReply:
    """Processa uma pergunta já persistida e entrega a resposta.

    Idempotente por design (ADR-0003): a tarefa Celery pode ser reentregue
    depois de o worker cair, e a mesma pergunta chegaria aqui de novo. Se já
    existe AIReply, a resposta já foi decidida e possivelmente entregue —
    refazer gastaria duas chamadas de modelo e uma consulta para dizer o
    mesmo, ou pior, algo diferente.
    """
    existente = AIReply.objects.filter(message=message).first()
    if existente is not None:
        return existente

    catalog = catalog or get_catalog()
    channel = channel or FakeChannel()
    provider = provider or FakeAIProvider(catalog)
    executor = executor or FakeQueryExecutor()
    auditoria = _Auditoria()

    try:
        decisao = _processar(message, provider, executor, catalog, auditoria)
    except AIQuotaExceeded as exc:
        # A conta da OpenAI ficou sem crédito (limite de gasto atingido). Não
        # é defeito nem instabilidade: o usuário recebe um aviso discreto para
        # procurar o time de BI, e o log fica em nível de erro para alguém
        # recarregar a conta.
        logger.error("Créditos da OpenAI esgotados: %s", exc)
        decisao = _Decisao(
            decision=AIReply.Decision.FAILED,
            reply=canned.SEM_CREDITOS,
            rule="sem_creditos_na_ia",
            raw={"erro": str(exc)},
            message_status=Message.Status.FAILED,
        )
    except AIProviderError as exc:
        # Fronteira com serviço externo: o usuário recebe um aviso legível e
        # a falha fica registrada, em vez de a exceção derrubar a tarefa.
        logger.warning("Falha do provedor de IA", exc_info=True)
        decisao = _Decisao(
            decision=AIReply.Decision.FAILED,
            reply=canned.FALHA_DA_IA,
            rule="falha_da_ia",
            raw={"erro": str(exc)},
            message_status=Message.Status.FAILED,
        )

    reply = _gravar(message, catalog, auditoria, decisao)

    if reply.reply_text:
        deliver_reply(channel, message.conversation, reply.reply_text, in_reply_to=message)

    return reply
