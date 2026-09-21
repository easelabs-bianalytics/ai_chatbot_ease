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
from dataclasses import dataclass, field, replace

from ai_orchestrator import ajuste_grafico, budget, canned
from ai_orchestrator.context import PEDIDO_DE_SECAO
from ai_orchestrator.grounding import check_grounding
from ai_orchestrator.models import AICall, AIReply, CatalogGap
from ai_orchestrator.providers.base import (
    AIProviderError,
    AIQuotaExceeded,
    AnswerRequest,
    HistoryMessage,
    ImageRequest,
    Plan,
    PlanRequest,
)
from ai_orchestrator.providers.fake import FakeAIProvider
from ai_orchestrator.prompts import PROMPT_VERSION
from ai_orchestrator.rules import apply_rules
from attachments import deposito, planilha as planilha_anexada
from attachments.limites import SEGUNDOS_DA_SAIDA, AnexoRecusado
from catalog.loader import get_catalog
from datasource.executors.base import (
    QueryExecutionError,
    QueryObjectMissing,
    QueryTimeout,
    QueryUnavailable,
)
from datasource.executors.fake import FakeQueryExecutor
from datasource.models import QueryRun
from datasource.sql_guard import validate_sql
from messaging.channels.fake import FakeChannel
from messaging.models import Message
from messaging.services import deliver_reply

logger = logging.getLogger(__name__)

DEFAULT_MAX_HISTORY_MESSAGES = 10
MAX_LINHAS_NA_TABELA = 20

# Linhas que a consulta do PREENCHIMENTO pode trazer. O limite normal do
# catálogo é 500, feito para o que o modelo vai ler; aqui ninguém lê — o
# resultado vai direto para as células —, e uma planilha de 20 mil linhas
# precisa de 20 mil chaves. É o mesmo limite da planilha de download.
LINHAS_DO_PREENCHIMENTO = 50_000


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
    # O que mais precisa ficar no registro da resposta, de etapas que não
    # decidem sozinhas (ex.: a imagem que virou planilha).
    extras: dict = field(default_factory=dict)

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


def _veio_do_documento_inteiro(plano) -> bool:
    return bool((plano.usage.request or {}).get("contexto_completo"))


def _planilha(message) -> str:
    """Resumo da planilha anexada, para TODA chamada ao planejador.

    Em 2026-09-21 a segunda chamada (documento inteiro) saía sem ele, e o
    modelo respondeu "não há planilha anexada" — depois de custar US$ 0,097.
    Um lugar só, para nenhuma chamada nova esquecer."""
    return message.anexo_resumo if message.anexo_tipo == Message.Anexo.PLANILHA else ""


def _executar_com_correcao(plano, message, provider, executor, catalog, auditoria, historico):
    """Valida e executa, com uma correção se der errado (ADR-0014).

    Devolve (plano, resultado, erro, falha). Resultado None significa que a
    consulta não saiu. `falha` diz quando não há o que corrigir:
    "inexistente" (o banco não tem a tabela ou o schema — o documento de
    referência manda não trocar por outra tabela parecida) ou "indisponivel"
    (o banco não respondeu — o SQL pode estar certo).
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
                    return plano, None, erro, "inexistente"
                if isinstance(exc, QueryUnavailable):
                    # O SQL pode estar certo: não há o que a IA corrigir.
                    return plano, None, erro, "indisponivel"
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
                return plano, resultado, "", ""

        if tentativa == 2:
            return plano, None, erro, ""

        tentativa += 1
        plano = provider.plan(
            PlanRequest(
                question=message.content, history=historico, error_note=erro,
                planilha=_planilha(message),
                # A correção usa o MESMO contexto do plano que está corrigindo.
                # Antes voltava ao recortado: um plano feito com o documento
                # inteiro e recusado pelo validador era "corrigido" sem as
                # regras que o produziram, e o modelo desistia (2026-09-21).
                full_context=_veio_do_documento_inteiro(plano),
            )
        )
        auditoria.chamada(AICall.Stage.FIX, plano.usage)
        if plano.intent != Plan.Intent.ANSWER_WITH_DATA or not plano.sql:
            # A IA desistiu na correção: não force uma terceira tentativa.
            return plano, None, erro, ""


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
        PlanRequest(
            question=message.content, history=historico, empty_note=NOTA_DE_VAZIO,
            planilha=_planilha(message),
        )
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


MAX_SUGESTOES = 3
MAX_LETRAS_SUGESTAO = 70


def _sugestoes(brutas, message) -> list:
    """Limpa as continuações que a redação propôs.

    Elas viram botão: frase longa quebra o layout, repetida confunde, e a
    que repete a pergunta que acabou de ser feita faz o usuário achar que o
    assistente não entendeu."""
    pergunta = " ".join(message.content.lower().split())
    limpas, vistas = [], set()
    for bruta in brutas or ():
        texto = " ".join(str(bruta or "").split())
        chave = texto.lower().rstrip("?.! ")
        if not texto or len(texto) > MAX_LETRAS_SUGESTAO or chave in vistas or chave in pergunta:
            continue
        vistas.add(chave)
        limpas.append(texto)
        if len(limpas) == MAX_SUGESTOES:
            break
    return limpas


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
    sugestoes = _sugestoes(resposta.followups, message)
    if sugestoes:
        extras["sugestoes"] = sugestoes
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


ROTULO_DA_IMAGEM = (
    "**Li a imagem que você enviou.** O que vem abaixo sai do que está nela, "
    "não do banco de dados da Ease Labs — não tenho como conferir esses "
    "números na base.\n\n"
)


def _ler_imagem(message, provider, auditoria, historico) -> _Decisao | None:
    """Caminho da imagem anexada (ADR-0024).

    Dois desfechos:

    - **A resposta está na imagem** (resumir, achar a maior queda, conferir
      uma conta): uma chamada ao modelo barato e fim. Sem planejador, sem
      banco, sem ancoragem — o que substitui a ancoragem é o rótulo, que diz
      na primeira linha que aquilo veio da imagem.
    - **A resposta está no banco** (preencher a tabela do print, conferir
      com o sell-out da empresa): a leitura vira pedido e o caminho normal
      segue. Devolve None nesse caso; a mensagem foi ajustada em memória por
      `_imagem_vira_pedido`.
    """
    dados = deposito.buscar(message.anexo_token)
    if dados is None:
        return _Decisao(
            decision=AIReply.Decision.FAILED,
            reply=canned.ANEXO_VENCIDO,
            rule="anexo_vencido",
            message_status=Message.Status.FAILED,
        )

    try:
        leitura = provider.read_image(
            ImageRequest(question=message.content, imagem_png=dados, history=historico)
        )
    finally:
        # Os bytes saem do depósito mesmo se a leitura falhar: nada de imagem
        # sobrando por quinze minutos porque o modelo caiu.
        deposito.descartar(message.anexo_token)

    auditoria.chamada(AICall.Stage.IMAGE, leitura.usage)

    if leitura.instrucoes_ignoradas:
        # Texto dentro da imagem tentando dar ordens (ADR-0021). O prompt do
        # leitor manda não obedecer; aqui fica o registro, que é o que
        # permite alguém olhar isso depois.
        logger.warning(
            "A imagem anexada continha instruções, ignoradas: %r",
            leitura.instrucoes_ignoradas[:200],
        )

    if leitura.precisa_do_banco and _imagem_vira_pedido(message, leitura, auditoria):
        return None

    texto = (leitura.resposta or "").strip()
    if _vazou_instrucoes(texto):
        logger.warning("A leitura da imagem repetiu o prompt; usando o texto de recusa")
        return _Decisao(
            decision=AIReply.Decision.OUT_OF_SCOPE,
            reply=canned.TENTATIVA_DE_INJECAO,
            rule="tentativa_de_injecao",
            raw={"rascunho": texto, "leitura": leitura.leitura},
        )

    return _Decisao(
        decision=AIReply.Decision.IMAGE_READING,
        reply=ROTULO_DA_IMAGEM + texto,
        raw={
            "leitura": leitura.leitura,
            "instrucoes_na_imagem": leitura.instrucoes_ignoradas,
            "anexo": message.anexo_nome,
        },
    )


# Nomes listados em cada grupo da nota. Uma planilha de 2 mil linhas sem
# correspondência não pode virar uma resposta de 2 mil nomes.
NOMES_NA_NOTA = 8


def _lista_curta(nomes) -> str:
    nomes = list(nomes)
    texto = ", ".join(nomes[:NOMES_NA_NOTA])
    if len(nomes) > NOMES_NA_NOTA:
        texto += f" e mais {len(nomes) - NOMES_NA_NOTA}"
    return texto


NOME_DA_TABELA_DO_PRINT = "tabela_do_print.xlsx"

# Quanto a planilha espera pela resposta a um "painel atual ou território?".
# Contado a partir da pergunta do Jarvis, não do envio.
SEGUNDOS_DA_PLANILHA_PENDENTE = 30 * 60


def _deixar_planilha_pendente(message) -> dict:
    """O Jarvis pediu um detalhe antes de preencher: a planilha espera.

    Sem isto, a resposta da pessoa ("painel atual") chegava sem anexo e o
    preenchimento nunca acontecia — achado no teste real de 2026-09-21. O
    prazo é renovado, e a etiqueta vai para o registro da resposta, que é
    onde a próxima mensagem procura (`_herdar_planilha_pendente`)."""
    if message.anexo_tipo != Message.Anexo.PLANILHA:
        return {}
    if not deposito.prolongar(message.anexo_token, segundos=SEGUNDOS_DA_PLANILHA_PENDENTE):
        return {}
    return {"planilha_pendente": {
        "nome": message.anexo_nome,
        "resumo": message.anexo_resumo,
        "token": message.anexo_token,
    }}


def _herdar_planilha_pendente(message, auditoria) -> None:
    """Se a última resposta desta conversa foi um pedido de detalhe sobre uma
    planilha, esta mensagem (a resposta da pessoa) herda a planilha.

    Só a ÚLTIMA resposta conta: se a conversa andou para outro assunto, a
    planilha não reaparece do nada. Herança em memória, como na imagem que
    vira planilha — no banco, a mensagem continua sem anexo."""
    anterior = (
        AIReply.objects.filter(message__conversation=message.conversation, message__id__lt=message.id)
        .order_by("-message__id")
        .first()
    )
    if anterior is None or anterior.decision != AIReply.Decision.CLARIFY:
        return
    pendente = (anterior.raw_response or {}).get("planilha_pendente")
    if not pendente or deposito.buscar(pendente.get("token", "")) is None:
        return
    message.anexo_tipo = Message.Anexo.PLANILHA
    message.anexo_nome = pendente["nome"]
    message.anexo_resumo = pendente["resumo"]
    message.anexo_token = pendente["token"]
    auditoria.extras["planilha_herdada_de"] = anterior.message_id


def _imagem_vira_pedido(message, leitura, auditoria) -> bool:
    """Transforma a leitura em pedido ao banco. False se não houver o que pedir.

    Com tabela a completar, ela vira uma planilha EM MEMÓRIA
    (`montar_de_tabela`) e o resto é o caminho da planilha: casamento de
    colunas pelo planejador, números do banco, arquivo para baixar. Sem
    tabela, a pergunta reformulada pela leitura vai ao planejador.

    A mensagem é ajustada só em memória, e isso é seguro por construção: o
    único `save` depois daqui é `update_fields=["status"]` (em
    `handle_message`), e o preenchimento grava seus campos com `update`. No
    banco, a pergunta continua sendo o que a pessoa escreveu, com a imagem —
    o teste `test_imagem_convertida_nao_altera_a_pergunta_gravada` garante.
    """
    registro = {"leitura": leitura.leitura}

    if leitura.tabela_colunas and leitura.tabela_linhas:
        try:
            dados = planilha_anexada.montar_de_tabela(leitura.tabela_colunas, leitura.tabela_linhas)
            estrutura = planilha_anexada.ler_estrutura(NOME_DA_TABELA_DO_PRINT, dados)
        except AnexoRecusado as exc:
            logger.info("A tabela do print não virou planilha: %s", exc)
        else:
            message.anexo_tipo = Message.Anexo.PLANILHA
            message.anexo_nome = NOME_DA_TABELA_DO_PRINT
            message.anexo_resumo = estrutura.resumo
            message.anexo_token = deposito.guardar(dados)
            auditoria.extras["imagem"] = {**registro, "virou": "planilha"}
            return True

    if leitura.pergunta_ao_banco:
        message.content = leitura.pergunta_ao_banco
        message.anexo_tipo = ""
        auditoria.extras["imagem"] = {**registro, "virou": "pergunta", "pergunta": leitura.pergunta_ao_banco}
        return True

    return False


def _nota_do_preenchimento(relatorio, nome: str) -> str:
    """Frase determinística sobre o preenchimento — escrita aqui, não pelo
    modelo. Custa zero token e não tem como exagerar o resultado.

    Diz, pelo nome, o que casou por aproximação (para conferir) e o que
    ficou em branco (para corrigir na planilha e mandar de novo)."""
    partes = [
        f"\n\n---\n\nPreenchi **{relatorio.preenchidas} de {relatorio.total} linhas** "
        f"de `{nome}`. Baixe pelo botão **Baixar planilha preenchida**."
    ]
    if relatorio.aproximadas:
        pares = [f"{planilha} → {banco}" for planilha, banco in relatorio.aproximadas]
        partes.append(
            f"\n\n**Casei por nome parecido — confira:** {_lista_curta(pares)}."
        )
    if relatorio.sem_correspondencia_nomes:
        partes.append(
            "\n\n**Ficaram em branco, sem correspondência no banco:** "
            f"{_lista_curta(relatorio.sem_correspondencia_nomes)}. Se algum for outro "
            "nome da mesma rede, ajuste na planilha e envie de novo."
        )
    if relatorio.ambiguas:
        partes.append(
            f"\n\n{relatorio.ambiguas} apareciam mais de uma vez no resultado; deixei em "
            "branco em vez de escolher uma."
        )
    return "".join(partes)


def _preencher_planilha(message, plano, executor, catalog, auditoria) -> str:
    """Preenche a planilha anexada com o resultado da consulta.

    Roda a consulta DE NOVO, com o limite alto: a que respondeu traz no
    máximo 500 linhas porque é o que o modelo lê, e a planilha pode ter vinte
    mil. Devolve a frase a acrescentar na resposta, ou vazio quando não deu
    para preencher — nesse caso a resposta em texto continua valendo.
    """
    dados = deposito.buscar(message.anexo_token)
    if dados is None:
        return "\n\n---\n\n" + canned.ANEXO_VENCIDO

    pedido = planilha_anexada.PedidoDePreenchimento.do_plano(plano.preenchimento)
    guard = validate_sql(plano.sql, catalog, max_rows=LINHAS_DO_PREENCHIMENTO)
    if not guard.approved:
        logger.warning("Consulta do preenchimento recusada pelo validador: %s", guard.reason)
        return ""

    try:
        resultado = executor.run(guard.sql, max_rows=LINHAS_DO_PREENCHIMENTO)
    except QueryExecutionError as exc:
        logger.warning("Consulta do preenchimento falhou: %s", exc)
        return ""

    auditoria.consulta(
        attempt=len(auditoria.consultas) + 1,
        sql=plano.sql,
        reference_query_id=plano.reference_query_id,
        guard_result=QueryRun.GuardResult.APPROVED,
        status=QueryRun.Status.SUCCESS,
        row_count=resultado.row_count,
        truncated=resultado.truncated,
        duration_ms=resultado.duration_ms,
        # Mesma forma da amostra das outras consultas: esta é a última da
        # resposta, e o painel de fonte e o gráfico leem dela.
        result_sample={
            "columns": list(resultado.columns),
            "rows": [list(linha) for linha in resultado.rows[:5]],
            "preenchimento": plano.preenchimento,
        },
    )

    try:
        preenchida = planilha_anexada.preencher(
            message.anexo_nome, dados, pedido, resultado.columns, resultado.rows
        )
    except AnexoRecusado as exc:
        logger.info("Não deu para preencher a planilha: %s", exc)
        return f"\n\n---\n\nNão consegui preencher a planilha: {exc}"
    finally:
        deposito.descartar(message.anexo_token)

    token = deposito.guardar(preenchida.dados, segundos=SEGUNDOS_DA_SAIDA)
    Message.objects.filter(pk=message.pk).update(
        anexo_resposta_token=token, anexo_resposta_nome=preenchida.nome
    )
    message.anexo_resposta_token = token
    message.anexo_resposta_nome = preenchida.nome
    return _nota_do_preenchimento(preenchida, preenchida.nome)


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


def _grafico_a_ajustar(message):
    """A última resposta desta conversa que tem gráfico na tela.

    Volta `(resposta, grafico, linhas)`. Sem gráfico à vista não há o que
    ajustar, e a mensagem segue o caminho normal."""
    anteriores = (
        Message.objects.filter(
            conversation_id=message.conversation_id,
            direction=Message.Direction.OUTBOUND,
            id__lt=message.pk,
        )
        .select_related("in_reply_to__ai_reply")
        .order_by("-id")[:5]
    )
    for anterior in anteriores:
        reply = getattr(getattr(anterior, "in_reply_to", None), "ai_reply", None)
        if reply is None:
            continue
        grafico = (reply.raw_response or {}).get("grafico")
        if not grafico:
            continue
        consulta = reply.query_runs.filter(status=QueryRun.Status.SUCCESS).order_by("-attempt").first()
        linhas = (consulta.result_sample or {}).get("rows") if consulta else None
        if linhas:
            return anterior, grafico, len(linhas)
    return None, None, 0


def _ajustar_grafico(message) -> _Decisao | None:
    """Troca o desenho sem consultar o banco nem chamar o modelo.

    Os números já estão na tela: refazer a consulta para trocar um tipo de
    gráfico gastaria duas chamadas de modelo e ainda poderia voltar um número
    diferente do que a pessoa está olhando."""
    ajuste = ajuste_grafico.ler_ajuste(message.content)
    if not ajuste:
        return None
    origem, grafico, total = _grafico_a_ajustar(message)
    if origem is None:
        return None

    novo = ajuste_grafico.aplicar(grafico, ajuste)
    return _Decisao(
        decision=AIReply.Decision.CONVERSATION,
        reply=ajuste_grafico.descrever(ajuste, total),
        rule="ajuste_de_grafico",
        raw={"grafico": novo, "grafico_de": origem.pk},
    )


def _processar(message, provider, executor, catalog, auditoria) -> _Decisao:
    regra = apply_rules(message.content, catalog)
    if regra is not None:
        return _Decisao(
            decision=regra.decision, reply=regra.reply, rule=regra.rule
        )

    ajustado = _ajustar_grafico(message)
    if ajustado is not None:
        return ajustado

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

    if message.anexo_tipo == Message.Anexo.IMAGEM:
        # Imagem é outro caminho, com um décimo do custo (ADR-0024) — a menos
        # que o pedido precise do banco; aí ela vira pergunta ou planilha e
        # o caminho normal segue daqui.
        decisao = _ler_imagem(message, provider, auditoria, historico)
        if decisao is not None:
            return decisao
    elif not message.anexo_tipo:
        _herdar_planilha_pendente(message, auditoria)

    plano = provider.plan(
        PlanRequest(
            question=message.content,
            history=historico,
            # Só a FORMA da planilha sobe ao modelo; o conteúdo fica aqui.
            planilha=_planilha(message),
        )
    )
    auditoria.chamada(AICall.Stage.PLAN, plano.usage)

    if _pediu_o_documento_inteiro(plano):
        # O contexto vai recortado por tema (ADR-0015). Quando o recorte não
        # basta, a IA avisa em vez de inventar a regra que faltou.
        logger.info("A IA pediu o documento inteiro: %s", plano.reason)
        plano = provider.plan(
            PlanRequest(
                question=message.content, history=historico, full_context=True,
                planilha=_planilha(message),
            )
        )
        auditoria.chamada(AICall.Stage.FIX, plano.usage)

    if plano.intent == Plan.Intent.CONVERSATION:
        return _conversa(plano, message, historico)

    if plano.intent == Plan.Intent.CLARIFY:
        return _Decisao(
            decision=AIReply.Decision.CLARIFY,
            reply=plano.clarification_question or canned.MENSAGEM_SEM_PERGUNTA,
            raw={"reason": plano.reason, **_deixar_planilha_pendente(message)},
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

    plano, resultado, erro, falha = _executar_com_correcao(
        plano, message, provider, executor, catalog, auditoria, historico
    )

    if falha == "indisponivel":
        # Não é lacuna do catálogo nem erro da IA: o banco não respondeu.
        return _Decisao(
            decision=AIReply.Decision.FAILED,
            reply=canned.BANCO_INDISPONIVEL,
            rule="banco_indisponivel",
            raw={"erro": erro},
            message_status=Message.Status.FAILED,
        )

    if falha == "inexistente":
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

    vai_preencher = message.anexo_tipo == Message.Anexo.PLANILHA and bool(plano.preenchimento)
    # Com planilha a preencher, o arquivo que importa é o da pessoa: a
    # redação não é instruída a mandar ao "Baixar Excel" (o botão do
    # resultado completo continua na tela, como segunda opção).
    plano_da_redacao = replace(plano, excel=False) if vai_preencher else plano
    texto, raw = _redigir(plano_da_redacao, resultado, message, provider, catalog, auditoria, historico)
    texto += _nota_de_truncamento(resultado, catalog.max_rows)

    if message.anexo_tipo == Message.Anexo.PLANILHA:
        if plano.preenchimento:
            texto += _preencher_planilha(message, plano, executor, catalog, auditoria)
            raw["preenchimento"] = plano.preenchimento
        else:
            # A consulta respondeu, mas o modelo não disse como casar as
            # colunas: a resposta em texto vale, e a planilha volta vazia.
            texto += "\n\n---\n\n" + canned.PLANILHA_SEM_CASAMENTO

    return _Decisao(
        decision=AIReply.Decision.ANSWERED,
        reply=texto,
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
        raw_response={**decisao.raw, **auditoria.extras},
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
