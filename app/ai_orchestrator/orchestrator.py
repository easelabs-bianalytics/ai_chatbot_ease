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

import datetime
import json
import logging
import numbers
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

from ai_orchestrator import ajuste_grafico, autocritica, budget, canned, limites, progresso, resumo
from ai_orchestrator.context import MAX_PASSOS_POR_RODADA, MAX_RODADAS, PEDIDO_DE_SECAO, secoes_do_pedido
from ai_orchestrator.grounding import _tem_suporte, check_grounding, check_grounding_varias, numeros_do_texto
from ai_orchestrator.models import AICall, AIReply, CatalogGap
from ai_orchestrator.providers.base import (
    AIOutputTruncated,
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
from ai_orchestrator import vega
from ai_orchestrator.rules import apply_rules
from attachments import anexo_sql, deposito, planilha as planilha_anexada, qa as conferencia_da_planilha
from attachments.limites import SEGUNDOS_DA_PLANILHA_NA_CONVERSA, SEGUNDOS_DA_SAIDA, AnexoRecusado
from attachments.planilha import COLUNA_DA_LINHA
from catalog.loader import get_catalog
from datasource.colunas import e_percentual
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

# Investigação (ADR-0025). Linhas de cada consulta que vão para a rodada
# seguinte e para a redação (as consultas são agregadas; isto é teto), e
# linhas guardadas para a tela desenhar as tabelas e gráficos dos blocos.
LINHAS_DOS_ACHADOS = 30
LINHAS_DOS_BLOCOS = 100

# Acima disto, a lista não é escrita pelo modelo: vira bloco de tabela, e ele
# recebe só uma amostra para comentar. Dez linhas ainda cabem num texto; 50
# viravam resposta cortada no meio (produção, 2026-09-21).
MAX_LINHAS_NO_TEXTO = 10
AMOSTRA_DA_LISTA_LONGA = 12


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


# Quantas respostas recentes levam o resumo do que as sustentou. A mais
# recente com dado leva também o SQL inteiro (ver `resumo.py`).
FONTES_NO_HISTORICO = 3


def _em_grupo(message) -> bool:
    conversa = message.conversation
    return getattr(conversa, "canal", "") == "whatsapp" and str(getattr(conversa, "whatsapp_jid", "")).endswith("@g.us")


def _com_autor(mensagem) -> str:
    """No grupo do WhatsApp várias pessoas perguntam na mesma conversa. Sem o
    nome de quem escreveu, o "e em julho?" do Bruno virava seguimento da
    pergunta da Ana (2026-09-30). O nome vai só para o modelo; no banco a
    pergunta continua como a pessoa escreveu."""
    autor = (getattr(mensagem, "autor_nome", "") or getattr(mensagem, "autor_externo", "") or "").strip()
    return f"[{autor}] {mensagem.content}" if autor else mensagem.content


def _pergunta(message) -> str:
    """A pergunta como vai ao planejador: com o autor, em grupo."""
    return _com_autor(message) if _em_grupo(message) else message.content


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
    mensagens = list(reversed(list(anteriores)))
    # Só as últimas respostas levam a fonte: é delas que o seguimento fala,
    # e o resumo de cada resposta antiga encheria o contexto.
    respostas = [m for m in mensagens if m.direction == Message.Direction.OUTBOUND][-FONTES_NO_HISTORICO:]
    fontes = {m.pk: _fonte_da_resposta(m) for m in respostas}
    # O SQL inteiro vai na última resposta que rodou consulta.
    ultima = next((m for m in reversed(respostas) if "- consulta" in fontes[m.pk]), None)
    if ultima is not None:
        fontes[ultima.pk] = _fonte_da_resposta(ultima, com_sql=True)
    grupo = _em_grupo(message)
    return tuple(
        HistoryMessage(
            direction=m.direction,
            text=_com_autor(m) if grupo and m.direction == Message.Direction.INBOUND else m.content,
            fonte=fontes.get(m.pk, ""),
        )
        for m in mensagens
    )


def _fonte_da_resposta(resposta, com_sql: bool = False) -> str:
    """O que sustentou uma resposta enviada, em campos (`resumo.py`)."""
    pergunta = getattr(resposta, "in_reply_to", None)
    reply = AIReply.objects.filter(message=pergunta).first() if pergunta is not None else None
    if reply is None:
        return ""
    if reply.rule == "ajuste_de_grafico":
        # O ajuste não rodou consulta: o que vale é o desenho novo.
        return resumo.resumir(reply)
    return resumo.resumir(reply, com_sql=com_sql)


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


def _redigir_sem_corte(provider, pedido):
    """A redação, com uma segunda chance quando ela vem cortada no limite de
    tokens: a mesma resposta, pedida mais enxuta.

    2026-09-25, WhatsApp: "o que é IC? Como está o IC da Ease em 2026? Crie
    uma visualização" estourou o limite e saiu só a tabela crua, sem a
    explicação e sem o gráfico — a consulta estava certa. Tentar de novo
    custa uma chamada ao modelo barato; a tabela crua custa a resposta."""
    try:
        return provider.answer(pedido)
    except AIOutputTruncated:
        logger.warning("A redação veio cortada no limite de tokens; tentando de novo, mais curta")
        return provider.answer(replace(pedido, mais_curta=True))


def _tabela(resultado) -> str:
    """Resultado em texto, sem narrativa nenhuma.

    É a saída de segurança quando a redação insiste em citar número sem
    suporte: o usuário continua recebendo o dado, só que sem frase em volta
    (ADR-0010)."""
    cabecalho = " | ".join(resultado.columns)
    linhas = [
        " | ".join(formatar_valor(v, c) for v, c in zip(linha, resultado.columns))
        for linha in resultado.rows[:MAX_LINHAS_NA_TABELA]
    ]
    texto = "\n".join([cabecalho, *linhas])
    total = resultado.row_count or len(resultado.rows)
    if total > len(linhas) or resultado.truncated:
        # Sem esta linha a lista parava na 20ª sem ninguém saber (2026-09-25).
        texto += (
            f"\n\n(Mostrando as {len(linhas)} primeiras de {total:,} linhas".replace(",", ".")
            + ("; a consulta ainda parou no limite, o total é maior" if resultado.truncated else "")
            + ". A lista inteira está no botão “Baixar Excel”.)"
        )
    return texto


def formatar_valor(valor, coluna=None) -> str:
    """Valor do banco para ler, no padrão brasileiro.

    Sem isto a tabela mostrava `7233.0` e `-234.87999999999982` — ruído de
    ponto flutuante que ninguém escreveu (caso real de 2026-09-21). Inteiro
    sem casa decimal; o resto com até duas casas, como a redação faz. Coluna
    de percentual sai com o símbolo: "9,23" sozinho não diz de quê."""
    if valor is None:
        return ""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return str(valor)
    if float(valor).is_integer():
        texto = f"{int(valor):,}".replace(",", ".")
    else:
        texto = f"{valor:,.2f}".rstrip("0").rstrip(".")
        texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{texto}%" if e_percentual(coluna) else texto


def _nota_de_truncamento(resultado, max_rows: int) -> str:
    if not resultado.truncated:
        return ""
    return (
        f"\n\n(Resultado cortado no limite de {max_rows} linhas: o que você vê "
        "é uma parte, não o total.)"
    )


def _tem_conversa_antes(message) -> bool:
    return Message.objects.filter(conversation=message.conversation, id__lt=message.id).exists()


def _responde_a_um_pedido_de_detalhe(message) -> bool:
    """A última resposta desta conversa foi uma pergunta do Jarvis."""
    anterior = (
        AIReply.objects.filter(message__conversation=message.conversation, message__id__lt=message.id)
        .order_by("-message__id")
        .values_list("decision", flat=True)
        .first()
    )
    return anterior == AIReply.Decision.CLARIFY


def _veio_do_documento_inteiro(plano) -> bool:
    return bool((plano.usage.request or {}).get("contexto_completo"))


def _planilha(message) -> str:
    """Resumo da planilha anexada, para TODA chamada ao planejador.

    Em 2026-09-21 a segunda chamada (documento inteiro) saía sem ele, e o
    modelo respondeu "não há planilha anexada" — depois de custar US$ 0,097.
    Um lugar só, para nenhuma chamada nova esquecer."""
    if message.anexo_tipo != Message.Anexo.PLANILHA:
        return ""
    if getattr(message, "planilha_da_conversa", False):
        return (
            "(Esta planilha foi enviada numa mensagem anterior desta conversa. Use-a se a "
            "pergunta falar dela; se a pergunta for outra, ignore-a.)\n\n" + message.anexo_resumo
        )
    return message.anexo_resumo


def _validar(sql, catalog, message, max_rows):
    """O validador, com as tabelas da planilha anexada liberadas (ADR-0031).

    Um lugar só: toda consulta desta resposta — a principal, a correção, a
    verificação do vazio, as hipóteses, as entregas e o preenchimento — pode
    citar `anexo.<aba>`, e nenhuma pode citar aba que não existe."""
    return validate_sql(sql, catalog, max_rows=max_rows, anexo=getattr(message, "tabelas_do_anexo", None) or ())


def _preparar_planilha(message, executor, auditoria):
    """Perfila a planilha da conversa e liga as abas dela à consulta.

    Devolve o executor que a conversa vai usar: com planilha, o que troca
    `anexo.<aba>` pelas linhas do arquivo (ADR-0031). O prazo da planilha é
    renovado a cada mensagem que chega com ela — ela acompanha a conversa,
    não só a primeira resposta. O perfil é refeito aqui, em memória: uma
    planilha enviada antes desta versão ganha os nomes das colunas no SQL."""
    message.tabelas_do_anexo = {}
    if message.anexo_tipo != Message.Anexo.PLANILHA:
        return executor
    dados = deposito.buscar(message.anexo_token)
    if dados is None:
        return executor
    deposito.prolongar(message.anexo_token, segundos=SEGUNDOS_DA_PLANILHA_NA_CONVERSA)
    try:
        estrutura = planilha_anexada.ler_estrutura(message.anexo_nome, dados)
    except AnexoRecusado as exc:
        logger.info("A planilha da conversa não pôde ser perfilada: %s", exc)
        return executor
    message.anexo_resumo = estrutura.resumo
    tabelas = anexo_sql.tabelas(estrutura)
    message.tabelas_do_anexo = tabelas
    # O token fica no registro para o "Baixar Excel" desta resposta refazer
    # a consulta que cita a planilha (`planilha_da_resposta.py`).
    auditoria.extras["anexo"] = {"token": message.anexo_token, "nome": message.anexo_nome, "tabelas": sorted(tabelas)}
    return anexo_sql.ExecutorComAnexo(executor, tabelas, auditoria.extras)


def _executar_com_correcao(plano, message, provider, executor, catalog, auditoria, historico):
    """Valida e executa, com uma correção se der errado (ADR-0014).

    Devolve (plano, resultado, erro, falha). Resultado None significa que a
    consulta não saiu. `falha` diz quando não há o que corrigir:
    "inexistente" (o banco não tem a tabela ou o schema — o documento de
    referência manda não trocar por outra tabela parecida) ou "indisponivel"
    (o banco não respondeu — o SQL pode estar certo).
    """
    # Numerada depois do que já rodou nesta resposta: na autocrítica a
    # consulta refeita é a 3ª ou 4ª, e a tela lê a última pela ordem.
    primeira = tentativa = len(auditoria.consultas) + 1
    while True:
        guard = _validar(plano.sql, catalog, message, catalog.max_rows)

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
            progresso.definir(message.pk, "Consultando o banco", etapa="consultando",
                              entendimento=plano.entendimento)
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

        if tentativa == primeira + 1:
            return plano, None, erro, ""

        tentativa += 1
        plano = provider.plan(
            PlanRequest(
                question=_pergunta(message), history=historico, error_note=erro,
                planilha=_planilha(message),
                # A correção usa o MESMO contexto do plano que está corrigindo.
                # Antes voltava ao recortado: um plano feito com o documento
                # inteiro e recusado pelo validador era "corrigido" sem as
                # regras que o produziram, e o modelo desistia (2026-09-21).
                full_context=_veio_do_documento_inteiro(plano), secoes_pedidas=_secoes_pedidas(plano),
            )
        )
        auditoria.chamada(AICall.Stage.FIX, plano.usage)
        if plano.intent != Plan.Intent.ANSWER_WITH_DATA or not plano.sql:
            # A IA desistiu na correção: não force uma terceira tentativa.
            return plano, None, erro, ""


NOTA_DE_VAZIO = (
    "A consulta rodou sem erro e não retornou nenhuma linha. Descubra o motivo: "
    "o valor que você filtrou pode não existir naquela coluna (caso mais comum em "
    "filtro de produto, categoria ou descrição — traga os valores que existem de "
    "verdade, com DISTINCT ou um LIKE mais curto), o nome pode não ter casado com "
    "o cadastro, a pessoa pode não estar ativa no período, ou o período pode não "
    "ter carga."
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
            question=_pergunta(message), history=historico, empty_note=NOTA_DE_VAZIO,
            planilha=_planilha(message),
        )
    )
    auditoria.chamada(AICall.Stage.FIX, plano.usage)
    if plano.intent != Plan.Intent.ANSWER_WITH_DATA or not plano.sql:
        return None, plano

    tentativa = len(auditoria.consultas) + 1
    guard = _validar(plano.sql, catalog, message, catalog.max_rows)
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


TIPOS_DE_GRAFICO = frozenset({"linha", "barras", "barras_horizontais", "area", "pizza"})
# Empilhar só faz sentido onde as partes somam um todo visível.
EMPILHAVEIS = frozenset({"barras", "barras_horizontais", "area"})
MAX_SERIES = 3


def _pediu_grafico(sugestao) -> bool:
    """A redação propôs um gráfico (e não "nenhum")."""
    sugestao = sugestao or {}
    return bool(sugestao.get("vega_lite")) or (sugestao.get("tipo") or "nenhum") not in ("", "nenhum")


def _grafico(sugestao, resultado, message, plano, motivos=None) -> dict | None:
    """Confere a sugestão de gráfico contra o resultado de verdade (ADR-0020).

    A IA só escolhe o tipo e as colunas; o desenho usa os números da
    consulta. Coluna inexistente, série que não é número ou resultado de uma
    linha só não viram gráfico — melhor nenhum gráfico do que um errado.

    Mas nunca em silêncio: em `motivos` vai o porquê de cada gráfico pedido
    que caiu, e a resposta diz isso à pessoa. Na conversa 18 (2026-09-23) o
    gráfico "um por especialidade" foi descartado sem aviso, o texto da
    redação afirmou que ele estava lá, e veio o primeiro 👎."""
    motivos = motivos if motivos is not None else []

    def recusar(motivo):
        if _pediu_grafico(sugestao):
            motivos.append(motivo)
        return None

    if not sugestao or resultado.row_count < 1:
        return None
    if sugestao.get("vega_lite"):
        # ADR-0026: qualquer gráfico, escrito em Vega-Lite. A especificação sai
        # daqui sem fonte de dado nem endereço; a tela injeta o resultado.
        spec = vega.validar(sugestao["vega_lite"], resultado.columns, resultado.rows, message.content, plano.sql)
        if spec is not None:
            titulo = " ".join(str(sugestao.get("titulo") or "").split())[:80]
            if titulo and not check_grounding(titulo, resultado.columns, resultado.rows, message.content, plano.sql).ok:
                titulo = ""
            return {"tipo": "vega", "vega": spec, "titulo": titulo}
        if sugestao.get("tipo") not in TIPOS_DE_GRAFICO:
            return recusar("a especificação do gráfico não bateu com as colunas do resultado")
    if sugestao.get("tipo") not in TIPOS_DE_GRAFICO:
        return recusar("o tipo de gráfico pedido não é um dos que a tela desenha")
    if resultado.row_count < 2:
        return recusar("o resultado tem uma linha só, e um número sozinho não vira gráfico")
    colunas = list(resultado.columns)
    x = sugestao.get("x")
    if x not in colunas:
        return recusar("o eixo do gráfico não é uma coluna do resultado")

    def numerica(nome):
        i = colunas.index(nome)
        valores = [linha[i] for linha in resultado.rows if linha[i] is not None]
        return bool(valores) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in valores
        )

    series = [s for s in dict.fromkeys(sugestao.get("series") or []) if s in colunas and s != x and numerica(s)]
    if not series:
        return recusar("o gráfico não tinha uma medida numérica do resultado")

    tipo = sugestao["tipo"]
    # Série por categoria (formato longo, "mês × especialidade × PX"): cada
    # valor da coluna de grupo vira uma série na tela. Foi o que faltou em
    # 2026-09-23 para "empilhe por especialidade" sair legível.
    grupo = ""
    if tipo != "pizza":
        grupo = _grupo_do_formato_longo(colunas, resultado.rows, x, series, sugestao.get("grupo") or "")
        if grupo is None:
            # O eixo repete e nenhuma coluna explica a repetição: cada mês
            # sairia duas vezes, com números que não se comparam.
            return recusar("o eixo se repete e nenhuma coluna do resultado separa as séries")
    if grupo or tipo == "pizza":
        series = series[:1]      # uma medida, repartida pelas categorias

    titulo = " ".join(str(sugestao.get("titulo") or "").split())[:80]
    if titulo and not check_grounding(titulo, resultado.columns, resultado.rows, message.content, plano.sql).ok:
        titulo = ""
    grafico = {"tipo": tipo, "x": x, "series": series[:MAX_SERIES], "titulo": titulo}
    if len(series) > MAX_SERIES:
        # A tela e a imagem do WhatsApp avisam: "3 de 5 séries" (2026-09-25).
        grafico["series_de_fora"] = series[MAX_SERIES:]
    if grupo:
        grafico["grupo"] = grupo
    if sugestao.get("empilhado") and tipo in EMPILHAVEIS and (grupo or len(series) > 1):
        grafico["empilhado"] = True
    if sugestao.get("separar") and (grupo or len(series) > 1) and tipo != "pizza":
        # Um gráfico por valor do grupo (ou por série), lado a lado e na
        # mesma escala.
        grafico["separar"] = True
        grafico.pop("empilhado", None)
    return grafico


# Teto de categorias para DEDUZIR um grupo que a redação não pediu: acima
# disto a coluna provavelmente é um identificador, não uma categoria. O grupo
# que a redação PEDIU vale com qualquer quantidade — a tela mostra as maiores
# e soma o resto em "Outras". Com o teto valendo para os dois, as ~30
# especialidades da conversa 18 derrubaram o gráfico pedido (2026-09-23).
MAX_VALORES_DO_GRUPO = 12


def _grupo_do_formato_longo(colunas, linhas, x, series, sugerido: str = ""):
    """A coluna que explica o eixo repetido, no formato longo.

    Em 2026-09-23 (conversa 14) o resultado era mês × categoria × PX, com a
    categoria em número (1 e 3). A redação não disse o grupo, e o gráfico
    saiu com cada mês duas vezes: 520 e 221 em jan, 617 e 257 em fev. Aqui o
    grupo é conferido e, quando falta, deduzido do próprio resultado: é a
    coluna que, junto com o eixo, identifica cada linha.

    Devolve o nome da coluna, "" quando o eixo não repete (não há grupo) ou
    None quando repete e nenhuma coluna explica — aí não há gráfico certo."""
    ix = colunas.index(x)
    com_eixo = [linha for linha in linhas if linha[ix] is not None]
    if len({str(linha[ix]) for linha in com_eixo}) == len(com_eixo):
        # Sem repetição, grupo só se a redação pediu e ele fizer sentido.
        return sugerido if _explica_o_eixo(colunas, com_eixo, ix, sugerido, series) else ""

    if _explica_o_eixo(colunas, com_eixo, ix, sugerido, series):
        return sugerido
    for nome in colunas:
        if nome != sugerido and _explica_o_eixo(colunas, com_eixo, ix, nome, series, deduzido=True):
            return nome
    return None


# Coluna numérica só é deduzida como categoria quando o nome diz que é código:
# "categoria" com 1 e 3 é CAT 1 e CAT 3; "qtd_pdvs" com 4 e 7 é medida.
_NOME_DE_CODIGO = re.compile(r"(?:^|_)(?:cat|categoria|cod|codigo|classe|tipo|grupo|faixa|segmento|nivel)(?:_|$)")


def _explica_o_eixo(colunas, linhas, ix, nome, series, deduzido: bool = False) -> bool:
    if not nome or nome not in colunas or nome in series or colunas.index(nome) == ix:
        return False
    ig = colunas.index(nome)
    valores = [linha[ig] for linha in linhas]
    distintos = {str(v) for v in valores}
    if len(distintos) < 2 or (deduzido and len(distintos) > MAX_VALORES_DO_GRUPO):
        return False
    numeros = [v for v in valores if isinstance(v, numbers.Number) and not isinstance(v, bool)]
    if numeros:
        # Número só é categoria quando é código inteiro (CAT 1, CAT 3);
        # decimal é medida, e medida não vira série. Deduzido sem a redação
        # pedir, ainda precisa ter nome de código.
        if any(v != int(v) for v in numeros):
            return False
        if deduzido and not _NOME_DE_CODIGO.search(nome.lower()):
            return False
    pares = {(str(linha[ix]), str(linha[ig])) for linha in linhas}
    return len(pares) == len(linhas)


def _avisar_grafico_que_caiu(extras: dict, motivos: list) -> None:
    """A redação pediu gráfico e nenhum sobrou: a resposta diz isso.

    O texto da redação foi escrito antes da conferência e costuma afirmar que
    o gráfico está lá ("está separada em um gráfico por especialidade"). A
    frase fica registrada em `aviso_de_grafico` e é acrescentada à resposta —
    a pessoa lê o que aconteceu, e o motivo vai para a auditoria."""
    tem_grafico = bool(extras.get("grafico")) or any(b.get("tipo") == "grafico" for b in extras.get("blocos") or ())
    if not motivos or tem_grafico:
        return
    aviso = f"_Não consegui desenhar o gráfico pedido: {motivos[0]}. Os números estão na tabela._"
    extras["aviso_de_grafico"] = aviso
    extras["motivos_do_grafico"] = motivos
    if extras.get("blocos"):
        extras["blocos"] = [*extras["blocos"], {"tipo": "texto", "texto": aviso}]


def _com_aviso(texto: str, extras: dict) -> str:
    """O texto da resposta com o aviso do gráfico que caiu, se houver: é o
    texto que vai para o histórico, para o WhatsApp e para quem lê sem blocos."""
    aviso = extras.get("aviso_de_grafico")
    return f"{texto}\n\n{aviso}" if aviso and aviso not in texto else texto


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


def _redigir(plano, resultado, message, provider, catalog, auditoria, historico, verificacao=False,
             nota_da_planilha=""):
    """Redige a resposta e confere a ancoragem numérica (ADR-0010).

    `nota_da_planilha`: o que a planilha devolvida recebeu (ADR-0031). A
    redação fala dela, e os números dela contam como fonte na ancoragem."""
    # Lista longa: o modelo não copia linha nenhuma. Ele recebe uma amostra,
    # escreve o texto e aponta a tabela; quem a desenha é a tela, com o
    # resultado do banco. Pedir a lista inteira ao modelo é o que estourava
    # o limite de saída — e, quando não estoura, é resposta paga para
    # transcrever o que já está no banco.
    lista_longa = not verificacao and resultado.row_count > MAX_LINHAS_NO_TEXTO
    progresso.definir(message.pk, "Escrevendo a resposta", etapa="escrevendo", entendimento=plano.entendimento)
    linhas = resultado.rows[: AMOSTRA_DA_LISTA_LONGA if lista_longa else catalog.rows_to_model]
    so_visual = not (verificacao or plano.excel) and ajuste_grafico.pedido_so_visual(message.content)
    pedido = AnswerRequest(
        question=message.content,
        sql=plano.sql,
        columns=resultado.columns,
        rows=linhas,
        truncated=resultado.truncated,
        reference_query_id=plano.reference_query_id,
        history=historico,
        total_rows=resultado.row_count,
        excel=plano.excel,
        verification=verificacao,
        tabela_em_bloco=lista_longa,
        entendimento=plano.entendimento,
        pedido_nao_atendido=plano.pedido_nao_atendido,
        so_visual=so_visual,
        planilha_devolvida=nota_da_planilha,
    )
    fonte_da_pergunta = "\n".join(filter(None, [message.content, nota_da_planilha]))
    try:
        resposta = _redigir_sem_corte(provider, pedido)
    except AIOutputTruncated:
        # A redação estourou o limite duas vezes (em produção, copiando 50
        # linhas numa tabela). O dado está aqui: sai a tabela.
        logger.warning("A redação veio cortada no limite de tokens duas vezes; enviando a tabela crua")
        return _tabela(resultado), {"rule": "resposta_sem_narrativa", "excel": plano.excel, "saida_cortada": True}
    auditoria.chamada(AICall.Stage.ANSWER, resposta.usage)

    extras = {"excel": plano.excel}
    # Ficam no registro para quem audita no Admin: quando a resposta erra o
    # seguimento, a primeira pergunta é se o planejador entendeu o pedido.
    for campo in ("entendimento", "pedido_nao_atendido"):
        if getattr(plano, campo):
            extras[campo] = getattr(plano, campo)
    sugestoes = _sugestoes(resposta.followups, message)
    if sugestoes:
        extras["sugestoes"] = sugestoes
    # Verificação não vira gráfico: o resultado é cadastral, e desenhá-lo
    # daria ao diagnóstico a aparência da resposta que não existe.
    motivos = []
    grafico = None if (plano.excel or verificacao) else _grafico(resposta.chart, resultado, message, plano, motivos)
    if grafico:
        extras["grafico"] = grafico
        _guardar_dados_do_grafico(auditoria, resultado)

    if (resposta.blocos or lista_longa) and not verificacao:
        # Resposta em blocos (ADR-0025): o gráfico vem de dentro deles, e a
        # tela desenha tabela e gráfico com os dados da consulta.
        blocos, dados = _validar_blocos(
            resposta.blocos, [(resultado, plano.sql)], message, motivos
        )
        if so_visual and blocos and grafico and not any(b["tipo"] == "grafico" for b in blocos):
            # O gráfico veio no formato simples, fora dos blocos: entra
            # neles, senão sairia só a tabela que ninguém pediu.
            blocos = [*blocos, {"tipo": "grafico", "consulta": 0, "grafico": grafico}]
            dados = {**dados, "0": _dados_da_consulta(resultado, inteiro=True, sql=plano.sql)}
        if so_visual and any(b["tipo"] == "grafico" for b in blocos):
            blocos = _so_o_visual(blocos)
        else:
            blocos, dados = _garantir_a_tabela(blocos, dados, resultado, lista_longa, resposta.reply, plano.sql)
        if blocos:
            extras.pop("grafico", None)
            extras["blocos"] = blocos
            extras["dados_blocos"] = dados
    _avisar_grafico_que_caiu(extras, motivos)

    conferencia = check_grounding(
        resposta.reply, resultado.columns, resultado.rows, fonte_da_pergunta, plano.sql,
        row_count=resultado.row_count,
    )
    if conferencia.ok:
        return resposta.reply, {"caveats": list(resposta.caveats), **extras}

    rascunhos = [resposta.reply]
    motivos = [conferencia.reason]

    try:
        reescrita = provider.answer(
            AnswerRequest(**{**pedido.__dict__, "revision_note": conferencia.reason})
        )
    except AIOutputTruncated:
        logger.warning("A reescrita veio cortada no limite de tokens; enviando a tabela crua")
        return _tabela(resultado), {"rule": "resposta_sem_narrativa", "excel": plano.excel, "saida_cortada": True}
    auditoria.chamada(AICall.Stage.REWRITE, reescrita.usage)

    segunda = check_grounding(
        reescrita.reply, resultado.columns, resultado.rows, fonte_da_pergunta, plano.sql,
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




def _ler_imagem(message, provider, auditoria, historico, critica: bool = False) -> _Decisao | None:
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
    if critica and texto and not _vazou_instrucoes(texto):
        # Print da resposta anterior com uma crítica: a leitura diz o que
        # está errado, e o caminho normal refaz (conversa 22). Em memória,
        # como em `_imagem_vira_pedido`: no banco fica o que a pessoa
        # escreveu, com a imagem.
        message.content = f"{message.content}\n\nO que o print da sua resposta anterior mostra: {texto}"
        message.anexo_tipo = ""
        auditoria.extras["imagem"] = {"leitura": leitura.leitura, "virou": "correcao"}
        return None
    if _vazou_instrucoes(texto):
        logger.warning("A leitura da imagem repetiu o prompt; usando o texto de recusa")
        return _Decisao(
            decision=AIReply.Decision.OUT_OF_SCOPE,
            reply=canned.TENTATIVA_DE_INJECAO,
            rule="tentativa_de_injecao",
            raw={"rascunho": texto, "leitura": leitura.leitura},
        )

    return _Decisao(
        # Quem avisa que isto saiu da imagem, e não do banco, é o rótulo
        # "Leitura da imagem" que a tela põe em toda resposta com esta
        # decisão. O parágrafo que repetia isso em palavras saía em todas as
        # leituras e empurrava a resposta para baixo.
        decision=AIReply.Decision.IMAGE_READING,
        reply=texto,
        raw={
            "leitura": leitura.leitura,
            "instrucoes_na_imagem": leitura.instrucoes_ignoradas,
            "anexo": message.anexo_nome,
        },
    )


# Nomes listados em cada grupo da nota. Uma planilha de 2 mil linhas sem
# correspondência não pode virar uma resposta de 2 mil nomes.
NOMES_NA_NOTA = 8


def _sem_repetir(nomes) -> list:
    """"17299140000105" cinco vezes vira "17299140000105 (5 linhas)": a
    planilha de cadastro repete a farmácia a cada atendente (Balcão Seguro,
    2026-10-01)."""
    contagem = {}
    for nome in nomes:
        contagem[nome] = contagem.get(nome, 0) + 1
    return [f"{nome} ({vezes} linhas)" if vezes > 1 else nome for nome, vezes in contagem.items()]


def _lista_curta(nomes) -> str:
    nomes = list(nomes)
    texto = ", ".join(nomes[:NOMES_NA_NOTA])
    if len(nomes) > NOMES_NA_NOTA:
        texto += f" e mais {len(nomes) - NOMES_NA_NOTA}"
    return texto


NOME_DA_TABELA_DO_PRINT = "tabela_do_print.xlsx"

# Quanto a planilha espera pela resposta a um "painel atual ou território?".
# Contado a partir da pergunta do Jarvis, não do envio. É o mesmo prazo da
# planilha na conversa (ADR-0031).
SEGUNDOS_DA_PLANILHA_PENDENTE = SEGUNDOS_DA_PLANILHA_NA_CONVERSA

# O que no registro de uma resposta mostra que ela usou a planilha.
_MARCAS_DE_USO_DA_PLANILHA = ("anexo_sql", "preenchimento", "planilha_alterada", "planilha_pendente")


def _usou_a_planilha(raw) -> bool:
    return any((raw or {}).get(marca) for marca in _MARCAS_DE_USO_DA_PLANILHA)


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


def _herdar_planilha_da_conversa(message, auditoria) -> None:
    """A planilha acompanha a conversa enquanto está guardada.

    2026-09-24, WhatsApp: a pessoa mandou a planilha com "O que existe nessa
    planilha?" e, na mensagem seguinte, "Mas você conseguiu ver o que existe
    dentro dela?" — o Jarvis respondeu que não havia planilha nenhuma, porque
    ela só seguia adiante depois de um pedido de esclarecimento. Agora a
    última planilha da conversa segue enquanto está no depósito (15 min
    depois de recebida, renovados a cada uso); o planejador é avisado de que
    ela veio antes e só a usa se a pergunta falar dela. Para de seguir quando
    a conversa muda de assunto — a primeira resposta com dado que não a usou
    — ou quando sai do depósito (duas horas sem uso).

    Preencher não encerra a planilha: na conversa 44 (2026-09-29) ela era
    descartada no primeiro preenchimento, e na correção seguinte ("use só os
    CRMs da planilha") o Jarvis pediu o arquivo de novo — e, reenviado,
    errou igual. Resposta que usou a planilha (consulta sobre `anexo.*`,
    preenchimento, aba nova) não conta como mudança de assunto."""
    _herdar_planilha_pendente(message, auditoria)
    if message.anexo_tipo:
        return
    anterior = (
        Message.objects.filter(
            conversation=message.conversation, id__lt=message.id,
            direction=Message.Direction.INBOUND, anexo_tipo=Message.Anexo.PLANILHA,
        )
        .order_by("-id")
        .first()
    )
    if anterior is None:
        return
    respostas = AIReply.objects.filter(
        message__conversation=message.conversation,
        message__id__gt=anterior.id, message__id__lt=message.id,
        decision=AIReply.Decision.ANSWERED,
    ).values_list("raw_response", flat=True)
    mudou_de_assunto = any(not _usou_a_planilha(raw) for raw in respostas)
    if mudou_de_assunto or not deposito.prolongar(anterior.anexo_token, segundos=SEGUNDOS_DA_PLANILHA_NA_CONVERSA):
        return
    message.anexo_tipo = Message.Anexo.PLANILHA
    message.anexo_nome = anterior.anexo_nome
    message.anexo_resumo = anterior.anexo_resumo
    message.anexo_token = anterior.anexo_token
    message.planilha_da_conversa = True
    auditoria.extras["planilha_da_conversa"] = anterior.pk


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
    partes.extend(_detalhes_do_preenchimento(relatorio))
    return "".join(partes)


def _detalhes_do_preenchimento(relatorio, prefixo: str = "") -> list:
    partes = []
    if relatorio.aproximadas:
        pares = [f"{planilha} → {banco}" for planilha, banco in relatorio.aproximadas]
        partes.append(f"\n\n**{prefixo}Casei por nome parecido — confira:** {_lista_curta(pares)}.")
    if relatorio.sem_correspondencia_nomes:
        partes.append(
            f"\n\n**{prefixo}Ficaram em branco, sem correspondência no banco:** "
            f"{_lista_curta(_sem_repetir(relatorio.sem_correspondencia_nomes))}. Se algum for outro "
            "nome da mesma rede, ajuste na planilha e envie de novo."
        )
    if relatorio.vazias_no_banco:
        partes.append(
            f"\n\n**{prefixo}Ficaram em branco, sem dado no banco:** {_lista_curta(_sem_repetir(relatorio.vazias_nomes))} "
            "(o identificador não está no cadastro, ou está sem esse dado)."
        )
    if relatorio.ambiguas:
        partes.append(
            f"\n\n{prefixo}{relatorio.ambiguas} apareciam mais de uma vez no resultado; deixei em "
            "branco em vez de escolher uma."
        )
    if relatorio.preservadas:
        partes.append(
            f"\n\n{prefixo}{relatorio.preservadas} células já tinham valor e foram mantidas. Para "
            "substituir, peça explicitamente."
        )
    if relatorio.sobrescritas:
        partes.append(f"\n\n{prefixo}{relatorio.sobrescritas} valores que já estavam lá foram substituídos, como pedido.")
    return partes


def _nota_das_abas(feitas, nome: str) -> str:
    """A nota do preenchimento com várias abas: quanto de cada uma, e o que
    conferir em cada uma."""
    contas = [f"**{r.preenchidas} de {r.total} linhas** da aba `{aba}`" for aba, r in feitas]
    partes = [
        f"\n\n---\n\nPreenchi {_lista_curta(contas)} de `{nome}`. "
        "Baixe pelo botão **Baixar planilha preenchida**."
    ]
    for aba, relatorio in feitas:
        partes.extend(_detalhes_do_preenchimento(relatorio, prefixo=f"Aba `{aba}`, "))
    return "".join(partes)


@dataclass
class _Alteracao:
    """O que aconteceu com a planilha da pessoa (ADR-0031).

    `texto` é a nota determinística que fecha a resposta; `relatorio`, o que
    a redação recebe para falar da planilha sem contradizê-la; `registro`,
    o que fica no AIReply."""

    texto: str = ""
    relatorio: str = ""
    registro: dict = field(default_factory=dict)
    # O resultado inteiro de cada consulta, quando ela teve de rodar de novo
    # com o limite do preenchimento: é ele que a redação e a tela devem ver.
    resultados: dict = field(default_factory=dict)


def _itens_da_planilha(plano) -> list:
    """O que o plano de uma consulta manda fazer no arquivo."""
    if not (plano.preenchimento or plano.aba_nova):
        return []
    return [{
        "sql": plano.sql, "referencia": plano.reference_query_id, "titulo": "",
        "preenchimento": plano.preenchimento or {}, "aba_nova": plano.aba_nova,
        "grafico_na_aba": plano.grafico_na_aba,
    }]


def _usa_a_planilha(plano) -> bool:
    """A consulta lê a planilha, ou o pedido é sobre ela sem escrever."""
    consultas = [plano.sql, *(c.get("sql", "") for c in plano.consultas)]
    return any(anexo_sql.referencias(sql) for sql in consultas) or plano.operacao_da_planilha in ("analisar", "descrever")


def _resultado_para_a_planilha(item, message, executor, catalog, auditoria, ja_executadas):
    """O resultado inteiro da consulta do item, ou o texto do erro.

    Reaproveita o que já rodou quando veio completo: consulta que parte de
    `anexo.<aba>` traz uma linha por linha da planilha e quase nunca passa
    das 500. Antes ela rodava sempre duas vezes (conversa 44). Só a que
    parou no limite roda de novo, com o limite do preenchimento."""
    pronto = ja_executadas.get(item["sql"])
    if pronto is not None and not pronto.truncated:
        return pronto
    guard = _validar(item["sql"], catalog, message, LINHAS_DO_PREENCHIMENTO)
    if not guard.approved:
        logger.warning("Consulta da planilha recusada pelo validador: %s", guard.reason)
        return f"a consulta foi recusada pelo validador ({guard.reason})"
    try:
        resultado = executor.run(guard.sql, max_rows=LINHAS_DO_PREENCHIMENTO)
    except QueryExecutionError as exc:
        logger.warning("Consulta da planilha falhou: %s", exc)
        return f"a consulta falhou ({exc})"
    auditoria.consulta(
        attempt=len(auditoria.consultas) + 1,
        sql=item["sql"],
        reference_query_id=item.get("referencia") or "",
        guard_result=QueryRun.GuardResult.APPROVED,
        status=QueryRun.Status.SUCCESS,
        row_count=resultado.row_count,
        truncated=resultado.truncated,
        duration_ms=resultado.duration_ms,
        # Mesma forma da amostra das outras consultas; a marca
        # "preenchimento" é o que a planilha de download usa para não tomar
        # esta pela consulta que responde.
        result_sample={
            "columns": list(resultado.columns),
            "rows": [list(linha) for linha in resultado.rows[:5]],
            "preenchimento": item.get("preenchimento") or {"aba_nova": item.get("aba_nova", "")},
        },
    )
    return resultado


def _origem_da_consulta(item) -> str:
    referencia = item.get("referencia") or ""
    return "consulta ao banco" + (f" (baseada na referência {referencia})" if referencia else "")


def _alterar_planilha(message, itens, executor, catalog, auditoria, ja_executadas=None) -> _Alteracao:
    """Aplica o que o plano pediu no arquivo da pessoa, confere e entrega.

    Cada item é {sql, referencia, preenchimento, aba_nova, grafico_na_aba}:
    colunas preenchidas (ENRICHMENT/UPDATE) e abas novas (REPORTING,
    TRANSFORMATION), todas no mesmo arquivo, com a aba "Notas do Jarvis"
    dizendo o que mudou e por quê. Antes de entregar, a conferência compara
    com o original e barra qualquer alteração fora do pedido. Resultado
    cortado no limite não é entregue: a planilha pela metade é pior que
    nenhuma (conversa 44: "Preenchi 84 de 230" com a consulta cortada)."""
    original = deposito.buscar(message.anexo_token)
    if original is None:
        return _Alteracao(texto="\n\n---\n\n" + canned.ANEXO_VENCIDO)

    progresso.definir(message.pk, "Montando a planilha", etapa="escrevendo")
    nome, dados = message.anexo_nome, original
    feitas, abas, recusas, cortadas, notas = [], [], [], [], []
    resultados = {}
    permissoes = {"_abas_novas": []}
    for item in itens:
        resultado = _resultado_para_a_planilha(item, message, executor, catalog, auditoria, ja_executadas or {})
        if isinstance(resultado, str):
            recusas.append(resultado)
            continue
        resultados[item["sql"]] = resultado
        if resultado.truncated:
            cortadas.append(item.get("aba_nova") or (item.get("preenchimento") or {}).get("aba") or "")
            continue
        if item.get("preenchimento"):
            try:
                pedido = planilha_anexada.PedidoDePreenchimento.do_plano(item["preenchimento"])
                feita = planilha_anexada.preencher(nome, dados, pedido, resultado.columns, resultado.rows)
            except (AnexoRecusado, KeyError) as exc:
                logger.info("Não deu para preencher a planilha: %s", exc)
                recusas.append(str(exc))
                continue
            dados, nome = feita.dados, feita.nome
            feitas.append(feita)
            regra = permissoes.setdefault(feita.aba, {"escrever": set(), "sobrescrever": set()})
            regra["escrever"] |= {destino for destino, _ in pedido.colunas}
            regra["sobrescrever"] |= set(pedido.sobrescrever)
            justificativas = dict(pedido.justificativas)
            for destino, origem in pedido.colunas:
                notas.append({
                    "onde": f"Aba {feita.aba or 'Dados'} · coluna {destino}",
                    "o_que": ("coluna nova" if destino in feita.criadas else "coluna existente, só as células vazias"
                              if destino not in pedido.sobrescrever else "coluna existente, valores substituídos"),
                    "por_que": justificativas.get(destino) or f"pedido: {message.content[:300]}",
                    "origem": f"coluna {origem} da {_origem_da_consulta(item)}",
                    "resultado": f"{feita.preenchidas} de {feita.total} linhas com valor",
                })
        if item.get("aba_nova"):
            try:
                dados, nome, titulo, com_grafico = planilha_anexada.adicionar_aba(
                    nome, dados, item["aba_nova"], resultado.columns, resultado.rows, item.get("grafico_na_aba", "")
                )
            except AnexoRecusado as exc:
                recusas.append(str(exc))
                continue
            permissoes["_abas_novas"].append(titulo)
            abas.append((titulo, resultado.row_count, com_grafico))
            notas.append({
                "onde": f"Aba nova {titulo}",
                "o_que": f"{resultado.row_count} linhas" + (", com gráfico" if com_grafico else ""),
                "por_que": item.get("titulo") or f"pedido: {message.content[:300]}",
                "origem": _origem_da_consulta(item),
                "resultado": "a base original não foi alterada",
            })

    registro = {"planilha_alterada": {"itens": len(itens), "preenchidas": len(feitas), "abas_novas": [a[0] for a in abas],
                                      "recusas": recusas, "cortadas": len(cortadas)}}
    if feitas and not abas and not any(f.preenchidas or f.sobrescritas for f in feitas):
        # Nenhuma célula escrita: devolver o mesmo arquivo com "Preenchi 0"
        # confunde, e a redação chegou a dizer que as 230 linhas estavam
        # vazias (2026-10-01). Sem mudança, sem arquivo.
        pedidas = sum(f.total for f in feitas)
        motivo = f"a consulta não trouxe valor para nenhuma das {pedidas} linhas pedidas"
        return _Alteracao(
            texto=f"\n\n---\n\nNão alterei a planilha: {motivo}.",
            registro=registro, relatorio=_relatorio_sem_alteracao(motivo), resultados=resultados,
        )
    if not feitas and not abas:
        # A redação precisa saber que NADA mudou: sem isto, ela escreveu "a
        # coluna Potencial foi preenchida" acima de "Não consegui preencher a
        # planilha" (2026-10-01) — a contradição da conversa 44 por outro lado.
        if cortadas:
            return _Alteracao(texto="\n\n---\n\n" + canned.PLANILHA_CORTADA, registro=registro,
                              relatorio=_relatorio_sem_alteracao(canned.PLANILHA_CORTADA))
        if recusas:
            return _Alteracao(texto=f"\n\n---\n\nNão consegui preencher a planilha: {recusas[0]}", registro=registro,
                              relatorio=_relatorio_sem_alteracao(recusas[0]))
        return _Alteracao(registro=registro)

    if Path(nome).suffix.lower() != ".csv":
        dados, nome = planilha_anexada.anotar(nome, dados, notas)
    conferencia = conferencia_da_planilha.conferir(message.anexo_nome, original, nome, dados, permissoes)
    registro["planilha_alterada"]["conferencia"] = conferencia.problemas
    if not conferencia.ok:
        # Defeito nosso, não da pessoa: nada sai, e o log grita.
        logger.error("A conferência barrou a planilha: %s", conferencia.problemas)
        return _Alteracao(
            texto="\n\n---\n\n" + canned.PLANILHA_BARRADA.format(motivo=conferencia.problemas[0]),
            registro=registro,
            relatorio=_relatorio_sem_alteracao("a conferência final barrou o arquivo"),
        )

    token = deposito.guardar(dados, segundos=SEGUNDOS_DA_SAIDA)
    Message.objects.filter(pk=message.pk).update(anexo_resposta_token=token, anexo_resposta_nome=nome)
    message.anexo_resposta_token = token
    message.anexo_resposta_nome = nome
    return _Alteracao(
        texto=_nota_da_planilha(feitas, abas, conferencia, nome, cortadas, recusas),
        relatorio=_relatorio_da_planilha(feitas, abas, conferencia, nome, cortadas, recusas),
        registro=registro,
        resultados=resultados,
    )


def _relatorio_sem_alteracao(motivo: str) -> str:
    return (
        f"A planilha NÃO foi alterada e nenhum arquivo foi devolvido. Motivo: {motivo}. "
        "Não diga que preencheu, atualizou ou criou nada no arquivo; diga o que a consulta "
        "mostrou e que a planilha não foi alterada."
    )


def _identificadores(message, preenchimentos) -> tuple:
    """(nome da coluna que identifica a linha, {_linha: valor}) da planilha
    da pessoa — o CRM de cada linha, por exemplo. Vazio se não houver."""
    for bruto in preenchimentos or []:
        chave = (bruto or {}).get("coluna_chave") or ""
        if not chave or planilha_anexada.normalizar(chave) == COLUNA_DA_LINHA:
            continue
        aba = planilha_anexada.normalizar((bruto or {}).get("aba") or "")
        for pagina in (getattr(message, "tabelas_do_anexo", None) or {}).values():
            if aba and planilha_anexada.normalizar(pagina.nome) != aba:
                continue
            i = next((k for k, c in enumerate(pagina.colunas)
                      if not c.interna and planilha_anexada.normalizar(c.nome) == planilha_anexada.normalizar(chave)), None)
            if i is not None:
                return pagina.colunas[i].nome, {numero: linha[i] for numero, linha in pagina.registros}
    return "", {}


def _tabelas_com_a_planilha_entregue(raw, message, preenchimentos) -> None:
    """A tabela da resposta quando a planilha da pessoa já foi devolvida.

    Conversa 52 (2026-10-01): o preenchimento saiu certo, e a tela mostrou
    100 de 230 linhas de `_linha · representante · gr` — números de linha do
    Excel e nomes soltos, sem dizer de que médico. Quem tem o arquivo não
    ganha nada com isso. Regra do Rubens: se a tabela não cabe inteira na
    mensagem, ela sai, e ficam o texto e o botão da planilha preenchida. Se
    cabe, o `_linha` vira o identificador da planilha (o CRM de cada linha),
    ou some quando não há identificador."""
    blocos = raw.get("blocos") or []
    dados = raw.get("dados_blocos") or {}
    if not blocos:
        return
    com_grafico = {str(b.get("consulta")) for b in blocos if b["tipo"] == "grafico"}
    nome, por_linha = _identificadores(message, preenchimentos)
    novos = []
    for bloco in blocos:
        if bloco["tipo"] != "tabela":
            novos.append(bloco)
            continue
        chave = str(bloco.get("consulta"))
        d = dados.get(chave) or {}
        total = d.get("total") or len(d.get("rows") or [])
        if d.get("truncado") or total > len(d.get("rows") or []):
            continue  # não cabe: o arquivo é a tabela
        colunas = d.get("columns") or []
        if COLUNA_DA_LINHA in colunas:
            i = colunas.index(COLUNA_DA_LINHA)
            if nome and chave not in com_grafico:
                dados[chave] = {
                    **d,
                    "columns": [nome if c == COLUNA_DA_LINHA else c for c in colunas],
                    "rows": [[por_linha.get(v, v) if k == i else v for k, v in enumerate(linha)] for linha in d["rows"]],
                }
                trocada = nome
            else:
                trocada = None
            pedidas = bloco.get("colunas") or colunas
            bloco = {**bloco, "colunas": [trocada if c == COLUNA_DA_LINHA else c for c in pedidas
                                          if c != COLUNA_DA_LINHA or trocada]}
        novos.append(bloco)
    if not novos:
        # Só havia a tabela: sem blocos, a tela mostra o texto da resposta.
        raw.pop("blocos", None)
        raw.pop("dados_blocos", None)
        return
    raw["blocos"] = novos
    raw["dados_blocos"] = dados


def _dominantes(conferencia) -> list:
    return [
        f"**{c.dominante}** aparece em {c.vezes_do_dominante} das {c.com_valor} linhas preenchidas de `{c.coluna}`"
        for c in conferencia.cobertura if c.dominante
    ]


def _nota_da_planilha(feitas, abas, conferencia, nome, cortadas, recusas) -> str:
    if len(feitas) == 1:
        texto = _nota_do_preenchimento(feitas[0], nome)
    elif feitas:
        texto = _nota_das_abas([(f.aba, f) for f in feitas], nome)
    else:
        texto = f"\n\n---\n\nDevolvi `{nome}`. Baixe pelo botão **Baixar planilha preenchida**."
    if abas:
        descritas = [f"`{titulo}` ({linhas} linhas{', com gráfico' if grafico else ''})" for titulo, linhas, grafico in abas]
        texto += f"\n\n**Abas novas:** {_lista_curta(descritas)}. A base original ficou como estava."
    if sum(len(f.criadas) + len(f.atualizadas) for f in feitas) > 1:
        # "Preenchi 513 de 513" contava a linha que ganhou QUALQUER valor — a
        # coluna "Critério" sempre tinha; a do representante, em 493 (Balcão
        # Seguro, 2026-10-01). Com várias colunas, cada uma diz a sua.
        texto += "\n\nPor coluna: " + " · ".join(
            f"`{c.coluna}` {c.com_valor} de {c.total}" for c in conferencia.cobertura
        ) + "."
    dominantes = _dominantes(conferencia)
    if dominantes:
        texto += "\n\n" + "; ".join(dominantes) + "."
    if cortadas:
        texto += "\n\n" + canned.PLANILHA_CORTADA
    if recusas:
        texto += "\n\nNão consegui fazer tudo: " + "; ".join(recusas)
    texto += "\n\nO que mudou e de onde veio cada dado está na aba **Notas do Jarvis**." if not nome.lower().endswith(".csv") else ""
    return texto


def _relatorio_da_planilha(feitas, abas, conferencia, nome, cortadas, recusas) -> str:
    """O mesmo que a nota, em texto corrido, para a redação."""
    linhas = [f"Arquivo devolvido: {nome}. A conferência comparou com o original: nenhuma célula original mudou."]
    for f in feitas:
        colunas = ", ".join(f.criadas) or "nenhuma"
        linhas.append(
            f"Aba {f.aba or 'única'}: colunas novas {colunas}; colunas existentes preenchidas "
            f"{', '.join(f.atualizadas) or 'nenhuma'}; {f.preenchidas} de {f.total} linhas ganharam valor; "
            f"{f.sem_correspondencia + f.vazias_no_banco} ficaram em branco por não haver dado no banco; "
            f"{f.ambiguas} com mais de um valor possível (em branco); {f.preservadas} valores que já existiam mantidos."
        )
    for c in conferencia.cobertura:
        extra = f"; valor mais comum {c.dominante!r} em {c.vezes_do_dominante}" if c.dominante else ""
        linhas.append(f"Coluna {c.coluna}: com valor em {c.com_valor} de {c.total} linhas{extra}.")
    for titulo, total, grafico in abas:
        linhas.append(f"Aba nova {titulo}: {total} linhas" + (", com gráfico." if grafico else "."))
    if cortadas:
        linhas.append("ALERTA: uma das consultas passou do limite de linhas e NÃO foi escrita na planilha.")
    for recusa in recusas:
        linhas.append(f"ALERTA: não foi possível fazer uma parte: {recusa}")
    return "\n".join(linhas)


# ---------------------------------------------------------------- investigação


def _investigar(plano, message, provider, executor, catalog, auditoria, historico) -> _Decisao:
    """Pergunta de porquê (ADR-0025): hipóteses em rodadas, depois a análise.

    Rodada 1: as hipóteses que o planejador escreveu. A cada rodada o
    planejador lê os achados e decide se aprofunda o ramo que eles
    apontaram ou se já dá para concluir. No máximo MAX_RODADAS chamadas ao
    planejador e MAX_PASSOS_POR_RODADA consultas por rodada: é o teto do
    custo. Consulta que falha não ganha correção própria — o erro vai nos
    achados, e o planejador reescreve na rodada seguinte se ela importar.
    """
    passos = []
    atual, rodada = plano, 1
    while True:
        for passo in atual.investigacao[:MAX_PASSOS_POR_RODADA]:
            # Entre uma hipótese e outra: é aqui que a parada economiza de
            # verdade — cada rodada custa uma chamada ao planejador e até
            # quatro consultas, e a análise final vem depois de todas.
            if foi_interrompida(message):
                return _interrompida()
            passos.append(_testar_hipotese(passo, rodada, message, executor, catalog, auditoria))
        if foi_interrompida(message):
            return _interrompida()
        if rodada >= MAX_RODADAS or atual.rodada_final:
            # O próprio planejador disse que estas consultas fecham a
            # investigação: a chamada seguinte só serviria para ele repetir
            # isso, e ela custa o mesmo que a primeira.
            break
        if _passou_do_teto(auditoria, f"rodada {rodada + 1} da investigação"):
            break
        progresso.definir(message.pk, "Lendo o que as consultas mostraram e decidindo o próximo passo")
        seguinte = provider.plan(PlanRequest(
            question=_pergunta(message),
            history=historico,
            planilha=_planilha(message),
            achados=_achados(passos),
            rodada=rodada + 1,
        ))
        auditoria.chamada(AICall.Stage.INVESTIGATE, seguinte.usage)
        if seguinte.intent != Plan.Intent.INVESTIGATE or not seguinte.investigacao:
            break
        atual, rodada = seguinte, rodada + 1

    registro = [
        {
            "rodada": p["rodada"],
            "hipotese": p["hipotese"],
            "sql": p["sql"],
            "linhas": p["resultado"].row_count if p["resultado"] is not None else None,
            "erro": p["erro"],
        }
        for p in passos
    ]
    com_dado = [p for p in passos if p["resultado"] is not None and p["resultado"].row_count > 0]
    if not com_dado:
        progresso.limpar(message.pk)
        return _Decisao(
            decision=AIReply.Decision.UNKNOWN,
            reply=canned.INVESTIGACAO_SEM_DADO,
            rule="investigacao_sem_dado",
            raw={"investigacao": registro},
            gap_reason="investigação sem consulta com dado: " + "; ".join(p["erro"] or "vazia" for p in passos),
        )

    progresso.definir(message.pk, "Escrevendo a análise", etapa="escrevendo")
    texto, raw = _redigir_analise(com_dado, message, provider, auditoria, historico)
    progresso.limpar(message.pk)
    return _Decisao(
        decision=AIReply.Decision.ANSWERED,
        reply=texto,
        rule=raw.pop("rule", ""),
        raw={**raw, "investigacao": registro, "rodadas": rodada},
    )


def _testar_hipotese(passo, rodada, message, executor, catalog, auditoria,
                     rotulo="Testando", etapa="investigando", entendimento="") -> dict:
    """Valida e executa a consulta de uma hipótese (ou de uma entrega).
    Registra sempre."""
    hipotese = passo.get("hipotese") or ""
    progresso.definir(message.pk, f"{rotulo}: {hipotese}" if hipotese else "Consultando os dados",
                      etapa=etapa, entendimento=entendimento)
    feito = {"rodada": rodada, "hipotese": hipotese, "sql": passo["sql"], "resultado": None, "erro": "",
             "falha": ""}
    registro = {
        "attempt": len(auditoria.consultas) + 1,
        "sql": passo["sql"],
        "reference_query_id": passo.get("reference_query_id", ""),
    }

    guard = _validar(passo["sql"], catalog, message, catalog.max_rows)
    if not guard.approved:
        auditoria.consulta(
            **registro,
            guard_result=QueryRun.GuardResult.REJECTED,
            guard_reason=guard.reason,
            status=QueryRun.Status.NOT_EXECUTED,
        )
        feito["erro"] = f"recusada pelo validador: {guard.reason}"
        return feito

    Message.objects.filter(pk=message.pk).update(status=Message.Status.PROCESSING)
    try:
        resultado = executor.run(guard.sql, max_rows=catalog.max_rows)
    except QueryExecutionError as exc:
        auditoria.consulta(
            **registro,
            guard_result=QueryRun.GuardResult.APPROVED,
            status=QueryRun.Status.TIMEOUT if isinstance(exc, QueryTimeout) else QueryRun.Status.ERROR,
            error=str(exc),
        )
        feito["erro"] = str(exc)
        if isinstance(exc, QueryUnavailable):
            feito["falha"] = "indisponivel"
        elif isinstance(exc, QueryObjectMissing):
            feito["falha"] = "inexistente"
        return feito

    auditoria.consulta(
        **registro,
        guard_result=QueryRun.GuardResult.APPROVED,
        status=QueryRun.Status.SUCCESS,
        row_count=resultado.row_count,
        truncated=resultado.truncated,
        duration_ms=resultado.duration_ms,
        result_sample={
            "columns": list(resultado.columns),
            "rows": [list(linha) for linha in resultado.rows[:5]],
            "hipotese": hipotese,
        },
    )
    feito["resultado"] = resultado
    return feito


def _achados(passos) -> str:
    """O que cada consulta mostrou, compacto, para a próxima rodada decidir."""
    partes = []
    for i, p in enumerate(passos):
        cabecalho = f"## Consulta {i} (rodada {p['rodada']}): {p['hipotese'] or 'sem hipótese declarada'}"
        if p["resultado"] is None:
            partes.append(f"{cabecalho}\nNão rodou: {p['erro']}")
            continue
        r = p["resultado"]
        linhas = [dict(zip(r.columns, linha)) for linha in r.rows[:LINHAS_DOS_ACHADOS]]
        partes.append(
            f"{cabecalho}\nColunas: {', '.join(r.columns)}\n"
            f"Linhas ({len(linhas)} de {r.row_count}): "
            f"{json.dumps(linhas, ensure_ascii=False, default=str)}"
        )
    return "\n\n".join(partes)


def _redigir_analise(com_dado, message, provider, auditoria, historico, plano=None, nota_da_planilha="") -> tuple:
    """A análise que cruza as consultas, conferida contra TODAS elas.

    Com `plano`, as consultas são as entregas de um pedido com várias
    (ADR-0026): a redação responde a cada uma, e cada uma aparece."""
    entregas = plano is not None
    consultas = tuple(
        {
            "hipotese": p["hipotese"],
            "titulo": p["hipotese"] if entregas else "",
            "sql": p["sql"],
            "columns": p["resultado"].columns,
            "rows": p["resultado"].rows[:LINHAS_DOS_ACHADOS],
            "total_rows": p["resultado"].row_count,
            "truncated": bool(p["resultado"].truncated),
        }
        for p in com_dado
    )
    pedido = AnswerRequest(
        question=message.content, sql="", columns=(), rows=(), truncated=False,
        history=historico, consultas=consultas, entregas=entregas,
        entendimento=plano.entendimento if entregas else "",
        pedido_nao_atendido=plano.pedido_nao_atendido if entregas else "",
        planilha_devolvida=nota_da_planilha,
    )
    fonte_da_pergunta = "\n".join(filter(None, [message.content, nota_da_planilha]))
    suporte = [(p["resultado"].columns, p["resultado"].rows, p["sql"], p["resultado"].row_count) for p in com_dado]
    fontes = [(p["resultado"], p["sql"]) for p in com_dado]

    rascunhos, motivos = [], []
    for tentativa in (1, 2):
        nota = motivos[-1] if motivos else ""
        try:
            resposta = provider.answer(replace(pedido, revision_note=nota) if nota else pedido)
        except AIOutputTruncated:
            logger.warning("A análise veio cortada no limite de tokens; enviando as evidências")
            break
        auditoria.chamada(AICall.Stage.ANSWER if tentativa == 1 else AICall.Stage.REWRITE, resposta.usage)
        conferencia = check_grounding_varias(resposta.reply, suporte, fonte_da_pergunta)
        if conferencia.ok:
            motivos_do_grafico = []
            blocos, dados = _validar_blocos(resposta.blocos, fontes, message, motivos_do_grafico)
            if entregas:
                blocos, dados = _garantir_as_entregas(blocos, dados, com_dado, resposta.reply)
            if ajuste_grafico.pedido_so_visual(message.content):
                blocos = _so_o_visual(blocos)
            extras = {"caveats": list(resposta.caveats)}
            sugestoes = _sugestoes(resposta.followups, message)
            if sugestoes:
                extras["sugestoes"] = sugestoes
            if blocos:
                extras["blocos"] = blocos
                extras["dados_blocos"] = dados
            _avisar_grafico_que_caiu(extras, motivos_do_grafico)
            if rascunhos:
                extras["rascunho_reprovado"] = rascunhos
                extras["motivos_ancoragem"] = motivos
            return _com_aviso(resposta.reply, extras), extras
        rascunhos.append(resposta.reply)
        motivos.append(conferencia.reason)

    # Duas reprovações: sem narrativa, mas com as evidências — cada hipótese
    # com a tabela que a testou, desenhada pela tela com os números do banco.
    logger.warning("Análise reprovada duas vezes na ancoragem; enviando as consultas sem narrativa")
    blocos, dados = [], {}
    for i, p in enumerate(com_dado):
        titulo = p["hipotese"]
        if titulo and not check_grounding(titulo, (), (), message.content, "").ok:
            titulo = ""
        blocos.append({"tipo": "tabela", "consulta": i, "colunas": _colunas_da_tabela(None, p["resultado"]), "titulo": titulo})
        dados[str(i)] = _dados_da_consulta(p["resultado"], sql=p["sql"])
    texto = (
        "Não consegui escrever o texto com segurança; estes são os resultados de cada parte do pedido:"
        if entregas else
        "Não consegui escrever a análise com segurança; estas são as consultas que fiz para investigar:"
    )
    return texto, {
        "rule": "entregas_sem_narrativa" if entregas else "analise_sem_narrativa",
        "blocos": [{"tipo": "texto", "texto": texto}, *blocos],
        "dados_blocos": dados,
        "rascunho_reprovado": rascunhos,
        "motivos_ancoragem": motivos,
    }


def _garantir_as_entregas(blocos, dados, com_dado, texto) -> tuple:
    """Toda entrega com dado aparece: a que a redação não apontou ganha uma
    tabela no fim. Pedir "a evolução e o ranking" e receber só um dos dois é
    o erro que as várias consultas vieram corrigir."""
    if not blocos:
        blocos = [{"tipo": "texto", "texto": texto}] if texto else []
    if not blocos:
        return [], {}
    blocos, dados = list(blocos), dict(dados)
    citadas = {b.get("consulta") for b in blocos if b["tipo"] != "texto"}
    for i, p in enumerate(com_dado):
        if i in citadas:
            continue
        bloco = {"tipo": "tabela", "consulta": i, "colunas": _colunas_da_tabela(None, p["resultado"], _texto_dos_blocos(blocos))}
        titulo = p["hipotese"]
        if titulo and check_grounding(titulo, (), (), "", "").ok:
            bloco["titulo"] = titulo
        blocos.append(bloco)
        dados.setdefault(str(i), _dados_da_consulta(p["resultado"], sql=p["sql"]))
    return blocos, dados


# ------------------------------------------------------- várias entregas

MAX_ENTREGAS = 4


def _entregar_varias(plano, message, provider, executor, catalog, auditoria, historico) -> _Decisao:
    """Pedido com entregas diferentes (ADR-0026, ponto B): uma consulta por
    entrega, cada uma validada e executada, e uma redação só.

    "A evolução prescritiva e o ranking das especialidades" (Paulo,
    2026-09-23) virou uma consulta com `UNION ALL`, meio vazia de cada lado.
    Aqui cada entrega tem a sua consulta e a sua tabela ou gráfico. Consulta
    que falha ganha uma correção própria, como a consulta comum (ADR-0014);
    entrega que não sai é dita na resposta, e as outras seguem."""
    passos = []
    alem = plano.consultas[MAX_ENTREGAS:]
    if alem:
        # Da 5ª em diante a entrega sumia sem aviso (2026-09-25).
        nota = (f"o pedido tinha {len(plano.consultas)} partes e respondi as {MAX_ENTREGAS} primeiras; ficaram de fora: "
                + "; ".join(f"«{c.get('titulo') or 'uma parte'}»" for c in alem))
        plano = replace(plano, pedido_nao_atendido="; ".join(filter(None, [plano.pedido_nao_atendido, nota])))
    for indice, consulta in enumerate(plano.consultas[:MAX_ENTREGAS]):
        if foi_interrompida(message):
            return _interrompida()
        passo = {"hipotese": consulta.get("titulo") or "", "sql": consulta["sql"],
                 "reference_query_id": consulta.get("reference_query_id") or ""}
        feito = _testar_hipotese(passo, 1, message, executor, catalog, auditoria,
                                 rotulo="Consultando", etapa="consultando", entendimento=plano.entendimento)
        if feito["falha"] == "indisponivel":
            return _Decisao(
                decision=AIReply.Decision.FAILED, reply=canned.BANCO_INDISPONIVEL,
                rule="banco_indisponivel", raw={"erro": feito["erro"]},
                message_status=Message.Status.FAILED,
            )
        if feito["resultado"] is None and not feito["falha"]:
            corrigida = _corrigir_entrega(plano, indice, passo, feito["erro"], message, provider, auditoria, historico)
            if corrigida:
                feito = _testar_hipotese({**passo, "sql": corrigida}, 1, message, executor, catalog, auditoria,
                                         rotulo="Consultando", etapa="consultando",
                                         entendimento=plano.entendimento)
        passos.append(feito)

    registro = [
        {"titulo": p["hipotese"], "sql": p["sql"],
         "linhas": p["resultado"].row_count if p["resultado"] is not None else None, "erro": p["erro"]}
        for p in passos
    ]
    com_dado = [p for p in passos if p["resultado"] is not None and p["resultado"].row_count > 0]
    if not com_dado:
        progresso.limpar(message.pk)
        erros = [p["erro"] for p in passos if p["erro"]]
        if erros:
            return _Decisao(
                decision=AIReply.Decision.FAILED,
                reply=canned.CONSULTA_NAO_APROVADA.format(motivo=erros[0]),
                rule="entregas_falharam", raw={"entregas": registro},
                message_status=Message.Status.FAILED,
                gap_reason="nenhuma entrega rodou: " + "; ".join(erros),
            )
        return _Decisao(
            decision=AIReply.Decision.EMPTY_RESULT, reply=canned.RESULTADO_VAZIO,
            rule="entregas_sem_linhas", raw={"entregas": registro},
        )

    faltaram = [
        f"«{p['hipotese'] or 'uma das partes'}» " + ("não rodou" if p["resultado"] is None else "voltou sem linhas")
        for p in passos if p not in com_dado
    ]
    if faltaram:
        nota = "estas partes do pedido não trouxeram dado: " + "; ".join(faltaram)
        plano = replace(plano, pedido_nao_atendido="; ".join(filter(None, [plano.pedido_nao_atendido, nota])))

    alteracao = _Alteracao()
    if message.anexo_tipo == Message.Anexo.PLANILHA:
        # Uma aba por consulta, todas no mesmo arquivo ("Preencha as duas",
        # WhatsApp, 2026-09-24), e abas novas de análise (ADR-0031). A
        # consulta vale como rodou (com a correção, se houve); a aba vem do
        # plano. A planilha sai ANTES da redação, que fala dela.
        itens = [
            {"sql": p["sql"], "referencia": consulta.get("reference_query_id") or "",
             "titulo": consulta.get("titulo") or "", "preenchimento": consulta.get("preenchimento") or {},
             "aba_nova": consulta.get("aba_nova") or "", "grafico_na_aba": consulta.get("grafico_na_aba") or ""}
            for p, consulta in zip(passos, plano.consultas)
            if p["resultado"] is not None and (consulta.get("preenchimento") or consulta.get("aba_nova"))
        ]
        if itens:
            alteracao = _alterar_planilha(message, itens, executor, catalog, auditoria,
                                          {p["sql"]: p["resultado"] for p in com_dado})

    progresso.definir(message.pk, "Escrevendo a resposta", etapa="escrevendo", entendimento=plano.entendimento)
    texto, raw = _redigir_analise(com_dado, message, provider, auditoria, historico, plano=plano,
                                  nota_da_planilha=alteracao.relatorio)
    progresso.limpar(message.pk)
    for campo in ("entendimento", "pedido_nao_atendido"):
        if getattr(plano, campo):
            raw[campo] = getattr(plano, campo)
    if alteracao.registro:
        texto += alteracao.texto
        raw.update(alteracao.registro)
        raw["preenchimento"] = [c["preenchimento"] for c in plano.consultas if c.get("preenchimento")]
        if alteracao.relatorio:
            _tabelas_com_a_planilha_entregue(raw, message, raw["preenchimento"])
    if plano.operacao_da_planilha:
        raw["operacao_da_planilha"] = plano.operacao_da_planilha
    return _Decisao(
        decision=AIReply.Decision.ANSWERED,
        reply=texto,
        rule=raw.pop("rule", ""),
        raw={**raw, "entregas": registro, "reference_query_id": plano.consultas[0].get("reference_query_id", "")},
    )


def _corrigir_entrega(plano, indice, passo, erro, message, provider, auditoria, historico) -> str:
    """Uma correção para a consulta de uma entrega. Devolve o SQL novo ou ""."""
    titulo = passo["hipotese"] or f"parte {indice + 1}"
    corrigido = provider.plan(PlanRequest(
        question=_pergunta(message), history=historico, planilha=_planilha(message),
        error_note=(
            f"O pedido tem várias entregas. A consulta da entrega «{titulo}» não pôde ser usada: "
            f"{erro}\n\nReescreva só a consulta dessa entrega, em `sql`."
        ),
        full_context=_veio_do_documento_inteiro(plano), secoes_pedidas=_secoes_pedidas(plano),
    ))
    auditoria.chamada(AICall.Stage.FIX, corrigido.usage)
    if corrigido.sql:
        return corrigido.sql
    for i, consulta in enumerate(corrigido.consultas):
        if consulta.get("titulo") == passo["hipotese"] or i == indice:
            return consulta["sql"]
    return ""


# ------------------------------------------------------- autocrítica


def _consulta_anterior(message) -> autocritica.Anterior | None:
    """A consulta que sustentou a última resposta com dado desta conversa."""
    run = (
        QueryRun.objects.filter(
            ai_reply__message__conversation=message.conversation,
            ai_reply__message__id__lt=message.id,
            status=QueryRun.Status.SUCCESS,
        )
        .order_by("-ai_reply__message__id", "-attempt", "-id")
        .first()
    )
    if run is None:
        return None
    amostra = run.result_sample or {}
    return autocritica.Anterior(
        colunas=tuple(amostra.get("columns") or ()),
        linhas=tuple(tuple(linha) for linha in amostra.get("rows") or ()),
        row_count=run.row_count or 0,
        sql=run.sql,
    )


def _sem_mudanca(plano):
    """A consulta final repete a anterior: a redação precisa saber, para
    explicar em vez de apresentar o mesmo número como novo."""
    if plano.pedido_nao_atendido:
        return plano
    return replace(plano, pedido_nao_atendido=autocritica.NAO_MUDOU)


def _voltar_para_a_consulta(auditoria, sql) -> None:
    """A consulta que vale vai para o fim da lista: a tela, o gráfico e o
    histórico leem a última que deu certo."""
    for i, consulta in enumerate(auditoria.consultas):
        if consulta.get("status") == QueryRun.Status.SUCCESS and consulta.get("sql") == sql:
            original = auditoria.consultas.pop(i)
            ultima = max((c.get("attempt") or 0) for c in auditoria.consultas) if auditoria.consultas else 0
            auditoria.consultas.append({**original, "attempt": ultima + 1})
            return


def _autocriticar(plano, resultado, message, provider, executor, catalog, auditoria, historico):
    """Seguimento que muda o dado e devolveu os mesmos números da resposta
    anterior: o planejador ganha uma segunda chance (`autocritica.py`).

    Devolve (plano, resultado) que valem. Se a segunda chance não produzir
    nada melhor, fica o primeiro — com o aviso à redação de que o número não
    mudou."""
    anterior = _consulta_anterior(message)
    if not autocritica.mesmo_resultado(resultado, anterior):
        return plano, resultado

    if _passou_do_teto(auditoria, "segunda chance da autocrítica"):
        return _sem_mudanca(plano), resultado
    logger.info("Seguimento com mudança de dado devolveu o resultado anterior; segunda chance")
    progresso.definir(message.pk, "O resultado saiu igual ao anterior; revendo a consulta",
                      etapa="conferindo", entendimento=plano.entendimento)
    segundo = provider.plan(PlanRequest(
        question=_pergunta(message), history=historico, planilha=_planilha(message),
        autocritica_note=autocritica.nota(plano.entendimento, anterior),
        full_context=_veio_do_documento_inteiro(plano), secoes_pedidas=_secoes_pedidas(plano),
    ))
    auditoria.chamada(AICall.Stage.SELF_CHECK, segundo.usage)
    registro = {"motivo": "mesmos números da resposta anterior", "refeita": False, "mudou": False}

    if segundo.intent != Plan.Intent.ANSWER_WITH_DATA or not segundo.sql or segundo.sql == plano.sql:
        auditoria.extras["autocritica"] = registro
        # O planejador manteve a consulta: o que ele disse sobre isso vale.
        if segundo.pedido_nao_atendido:
            plano = replace(plano, pedido_nao_atendido=segundo.pedido_nao_atendido)
        return _sem_mudanca(plano), resultado

    novo_plano, novo, erro, _ = _executar_com_correcao(
        segundo, message, provider, executor, catalog, auditoria, historico
    )
    registro["refeita"] = True
    if novo is None or novo.row_count == 0:
        auditoria.extras["autocritica"] = {**registro, "erro": erro or "a consulta refeita voltou sem linhas"}
        _voltar_para_a_consulta(auditoria, plano.sql)
        return _sem_mudanca(plano), resultado

    registro["mudou"] = not autocritica.mesmo_resultado(novo, anterior)
    auditoria.extras["autocritica"] = registro
    return (novo_plano if registro["mudou"] else _sem_mudanca(novo_plano)), novo


def _so_as_linhas_da_planilha(resultado, plano, message):
    """Reduz o resultado às chaves da planilha, na ordem dela.

    Se a planilha venceu, ou se nenhuma chave casou, devolve o resultado
    como veio: melhor a resposta falar demais do que não falar nada."""
    if COLUNA_DA_LINHA in resultado.columns:
        # A consulta partiu de `anexo.<aba>`: já é uma linha por linha da
        # planilha, na ordem dela.
        return resultado
    dados = deposito.buscar(message.anexo_token)
    if dados is None:
        return resultado
    try:
        pedido = planilha_anexada.PedidoDePreenchimento.do_plano(plano.preenchimento)
        escolhidas = planilha_anexada.linhas_das_chaves(
            message.anexo_nome, dados, pedido, resultado.columns, resultado.rows
        )
    except (AnexoRecusado, KeyError, ValueError) as exc:
        logger.info("Não deu para reduzir o resultado às linhas da planilha: %s", exc)
        return resultado
    if not escolhidas:
        return resultado
    # O aviso de corte continua: chave além do limite de linhas sumiria da
    # resposta sem ninguém saber (2026-09-25).
    return replace(resultado, rows=tuple(escolhidas))


def _so_o_visual(blocos) -> list:
    """Pedido só visual com o gráfico desenhado: sai a tabela da mesma
    consulta (conversa 18). Se o gráfico tivesse caído, a tabela ficaria —
    melhor os dados sem desenho do que resposta nenhuma."""
    desenhadas = {b.get("consulta") for b in blocos if b["tipo"] == "grafico"}
    return [b for b in blocos if not (b["tipo"] == "tabela" and b.get("consulta") in desenhadas)]


def _garantir_a_tabela(blocos, dados, resultado, lista_longa: bool, texto: str, sql: str = "") -> tuple:
    """Lista longa sem bloco de tabela: acrescenta um no fim.

    A instrução pede ao modelo que aponte a tabela em vez de copiar as
    linhas. Se ele não apontar, a pessoa ficaria com um texto que fala de
    uma lista que não está em lugar nenhum — então a tabela entra aqui, com
    os dados do banco."""
    if not lista_longa or any(b["tipo"] == "tabela" for b in blocos):
        return blocos, dados
    if not blocos:
        blocos = [{"tipo": "texto", "texto": texto}] if texto else []
    if not blocos:
        return [], {}
    blocos = [*blocos, {"tipo": "tabela", "consulta": 0, "colunas": _colunas_da_tabela(None, resultado, _texto_dos_blocos(blocos))}]
    return blocos, {**dados, "0": _dados_da_consulta(resultado, sql=sql)}


# A partir de quantas linhas uma coluna constante é resumo repetido, e não
# informação da linha. Com uma ou duas, a "constante" pode ser a própria
# resposta.
LINHAS_PARA_PODAR_CONSTANTE = 3


_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _resumo_repetido(valor, texto: str) -> bool:
    """O valor constante de uma coluna é resumo da análise, e não dado da
    linha: uma data (a de corte, o último mês realizado) ou um número que o
    texto já cita. Número constante que o texto não cita fica — "todos os CDs
    com DDE 0" é a informação da lista, não um resumo."""
    if isinstance(valor, (datetime.date, datetime.datetime)) or (isinstance(valor, str) and _DATA_ISO.match(valor)):
        return True
    if isinstance(valor, bool) or not isinstance(valor, numbers.Number):
        return False
    return any(_tem_suporte(token, candidatos, {float(valor)}) for token, candidatos in numeros_do_texto(texto))


def _texto_dos_blocos(blocos) -> str:
    return "\n".join(b.get("texto") or "" for b in blocos if b.get("tipo") == "texto")


def _colunas_da_tabela(pedidas, resultado, texto: str = "") -> list:
    """As colunas que a tabela mostra: as pedidas (ou todas), sem as que só
    repetem um resumo em todas as linhas.

    Conversa 24 (2026-09-24): a projeção de PX saiu com nove colunas, cinco
    delas o mesmo valor repetido nas doze linhas (a variação da reta, o
    último mês realizado, o realizado no ano, o projetado restante e o total).
    A consulta as repete para a redação citar; na tabela são ruído, e o valor
    já está no texto. A planilha continua com todas."""
    colunas = [c for c in pedidas or [] if c in resultado.columns] or list(resultado.columns)
    linhas = resultado.rows
    if len(linhas) < LINHAS_PARA_PODAR_CONSTANTE:
        return colunas
    indice = {c: i for i, c in enumerate(resultado.columns)}
    ficam = []
    for c in colunas:
        valores = {repr(linha[indice[c]]) for linha in linhas}
        if len(valores) == 1 and _resumo_repetido(linhas[0][indice[c]], texto):
            continue
        ficam.append(c)
    # Tudo resumo é um resultado estranho, mas não uma tabela vazia.
    return ficam or colunas


def _dados_da_consulta(resultado, inteiro: bool = False, sql: str = "") -> dict:
    """As linhas que a tela recebe. Tabela: as primeiras (a lista inteira está
    na planilha). Gráfico: o resultado inteiro — com 237 linhas ordenadas por
    especialidade, as 100 primeiras desenhavam só as especialidades de A a C
    (conversa 18, 2026-09-23).

    `sql` é a consulta DESTA tabela: a planilha dela (Baixar Excel, arquivo
    do WhatsApp) refaz exatamente essa, e não "a última que rodou" — com
    várias consultas na resposta, a última era de outra tabela, e a planilha
    saía com 100 linhas ou com o dado errado (2026-09-25). `truncado` diz que
    a consulta parou no limite de linhas da conversa."""
    linhas = resultado.rows if inteiro else resultado.rows[:LINHAS_DOS_BLOCOS]
    return {"columns": list(resultado.columns), "rows": [list(linha) for linha in linhas],
            "total": resultado.row_count, "sql": sql, "truncado": bool(resultado.truncated)}


def _validar_blocos(blocos, fontes, message, motivos=None) -> tuple:
    """Confere cada bloco contra as consultas de verdade (ADR-0025).

    `fontes` é [(resultado, sql)], na ordem dos índices que a redação usou.
    Tabela e gráfico que apontam consulta inexistente, coluna que não existe
    ou série que não é número caem — melhor um bloco a menos do que um
    errado. Devolve (blocos, dados das consultas que eles usam)."""
    validos, dados = [], {}
    texto_da_resposta = _texto_dos_blocos(blocos or ())
    for bloco in blocos or ():
        tipo = bloco.get("tipo")
        if tipo == "texto":
            validos.append({"tipo": "texto", "texto": bloco["texto"]})
            continue
        indice = bloco.get("consulta")
        if not isinstance(indice, int) or not 0 <= indice < len(fontes):
            continue
        resultado, sql = fontes[indice]
        if tipo == "tabela":
            if resultado.row_count < 1:
                continue
            colunas = _colunas_da_tabela(bloco.get("colunas"), resultado, texto_da_resposta)
            validos.append({"tipo": "tabela", "consulta": indice, "colunas": colunas})
        elif tipo == "grafico":
            grafico = _grafico(bloco.get("grafico"), resultado, message, SimpleNamespace(sql=sql), motivos)
            if not grafico:
                continue
            validos.append({"tipo": "grafico", "consulta": indice, "grafico": grafico})
            dados[str(indice)] = _dados_da_consulta(resultado, inteiro=True, sql=sql)
            continue
        else:
            continue
        dados.setdefault(str(indice), _dados_da_consulta(resultado, sql=sql))

    # Sem texto nenhum não é resposta: a redação comum volta ao formato antigo.
    if not any(b["tipo"] == "texto" for b in validos):
        return [], {}
    return validos, dados


def _consultas_anteriores(message, limite: int = 10) -> list:
    """(columns, rows, sql, row_count) das consultas que já rodaram nesta
    conversa, da mais recente para trás."""
    execucoes = QueryRun.objects.filter(
        ai_reply__message__conversation=message.conversation,
        ai_reply__message__id__lt=message.id,
        status=QueryRun.Status.SUCCESS,
    ).order_by("-id")[:limite]
    return [
        (
            (q.result_sample or {}).get("columns") or (),
            (q.result_sample or {}).get("rows") or (),
            q.sql,
            q.row_count,
        )
        for q in execucoes
    ]


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
    # O resumo da planilha também é fonte: "4 linhas", "AGO/26", as redes e os
    # representantes que ela traz. Sem isto, em 2026-09-24 a descrição certa
    # de "O que existe nessa planilha?" virou o texto de reserva.
    contexto = "\n".join([message.content, _planilha(message), *(m.text for m in historico)])
    # Os números das consultas anteriores desta conversa também valem: "qual
    # MAT você considerou?" se responde com o período que estava no SQL e no
    # resultado da resposta anterior, não no texto dela. Sem isto, em
    # 2026-09-23 a resposta certa ("set/2025 a ago/2026") virou o texto de
    # reserva duas vezes seguidas, e o Jarvis pareceu não entender a pergunta.
    consultas = [((), (), "", None), *_consultas_anteriores(message)]
    if texto and check_grounding_varias(texto, consultas, contexto).ok:
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


# Teto de custo de UMA pergunta, em dólares (AI_MAX_COST_PER_QUESTION).
# Passou dele, as chamadas opcionais param: rodada a mais de investigação,
# segunda chance da autocrítica, verificação do resultado vazio e o documento
# inteiro. A pergunta comum custa US$ 0,03 a 0,07; o teto é contra o caso
# que dispara — uma de US$ 0,30 em 2026-10-01 quebrava a conta do mês.
TETO_PADRAO_POR_PERGUNTA = 0.15


def _teto_por_pergunta() -> float:
    try:
        valor = float(os.environ.get("AI_MAX_COST_PER_QUESTION", "").strip())
    except ValueError:
        return TETO_PADRAO_POR_PERGUNTA
    return valor if valor > 0 else TETO_PADRAO_POR_PERGUNTA


def _passou_do_teto(auditoria, etapa: str) -> bool:
    """A pergunta já custou o teto: a etapa opcional não roda, e fica no
    registro qual foi cortada."""
    gasto = auditoria.totais["cost_estimate"]
    if gasto < _teto_por_pergunta():
        return False
    logger.warning("Teto por pergunta atingido (US$ %.3f): %s não roda", gasto, etapa)
    auditoria.extras.setdefault("teto_por_pergunta", []).append(etapa)
    return True


def _secoes_pedidas(plano) -> tuple:
    """As seções que um plano recebeu por pedido, para a correção dele usar
    as mesmas — senão ela voltava ao recorte que não bastou."""
    return tuple((plano.usage.request or {}).get("secoes_pedidas") or ())


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

    Volta `(origem, grafico, dados, consulta)`: `origem` é a resposta que
    rodou a consulta, `dados` o resultado que desenha o gráfico e `consulta`
    o índice do bloco de onde ele veio (None no gráfico solto). Sem gráfico à
    vista não há o que ajustar, e a mensagem segue o caminho normal.

    Resposta em blocos também conta: em 2026-09-23 o gráfico da conversa 14
    estava num bloco, a regra não o via, e "quero ver CAT 1 e CAT 3 de forma
    separada" foi para o modelo, que refez a consulta e devolveu o mesmo
    desenho."""
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
        achado = _grafico_da_resposta(anterior)
        if achado is not None:
            return achado
    return None, None, {}, None


def _grafico_da_resposta(resposta, profundidade: int = 0):
    """`(origem, grafico, dados, consulta)` de uma resposta enviada, ou None."""
    reply = getattr(getattr(resposta, "in_reply_to", None), "ai_reply", None)
    if reply is None:
        return None
    raw = reply.raw_response or {}
    do_bloco = [b for b in raw.get("blocos") or () if b.get("tipo") == "grafico"]
    if do_bloco:
        bloco = do_bloco[-1]
        dados = (raw.get("dados_blocos") or {}).get(str(bloco.get("consulta"))) or {}
        return (resposta, bloco.get("grafico") or {}, dados, bloco.get("consulta")) if dados.get("rows") else None
    grafico = raw.get("grafico")
    if not grafico:
        return None
    if raw.get("grafico_de"):
        # Ajuste de um ajuste ("muda para barras", depois "separa"): os dados
        # continuam na resposta que rodou a consulta; o desenho é o mais novo.
        origem = (
            Message.objects.filter(pk=raw["grafico_de"]).select_related("in_reply_to__ai_reply").first()
            if profundidade < 5 else None
        )
        achado = _grafico_da_resposta(origem, profundidade + 1) if origem is not None else None
        if achado is None:
            return None
        return achado[0], grafico, achado[2], raw.get("grafico_de_consulta", achado[3])
    consulta = reply.query_runs.filter(status=QueryRun.Status.SUCCESS).order_by("-attempt").first()
    dados = (consulta.result_sample or {}) if consulta else {}
    return (resposta, grafico, dados, None) if dados.get("rows") else None


def _ajustar_grafico(message) -> _Decisao | None:
    """Troca o desenho sem consultar o banco nem chamar o modelo.

    Os números já estão na tela: refazer a consulta para trocar um tipo de
    gráfico gastaria duas chamadas de modelo e ainda poderia voltar um número
    diferente do que a pessoa está olhando."""
    ajuste = ajuste_grafico.ler_ajuste(message.content)
    if not ajuste:
        return None
    origem, grafico, dados, indice = _grafico_a_ajustar(message)
    if origem is None or grafico.get("tipo") == "vega":
        # Trocar o desenho de uma especificação Vega-Lite é reescrevê-la:
        # isso é com a IA, que conhece os campos.
        return None

    if ajuste.get("separar") is False and not grafico.get("separar") and len(ajuste) == 1:
        # "Juntar" um gráfico que já está junto não é ajuste de desenho: é
        # outra coisa ("junta o estoque"), e quem resolve é a IA.
        return None

    novo = ajuste_grafico.aplicar(grafico, ajuste)
    colunas, linhas = list(dados.get("columns") or ()), dados.get("rows") or ()
    if novo.get("x") in colunas and novo.get("tipo") != "pizza" and len(novo.get("series") or []) <= 1:
        # O gráfico de antes pode ter saído sem grupo (é o caso da conversa
        # 14): o ajuste confere de novo, com o mesmo resultado. Só com uma
        # série: com várias, o grupo trocaria as séries e sumiria com elas.
        grupo = _grupo_do_formato_longo(colunas, linhas, novo["x"], novo.get("series") or [], novo.get("grupo") or "")
        if grupo:
            novo["grupo"] = grupo
    if ajuste.get("separar") and not novo.get("grupo") and len(novo.get("series") or []) < 2:
        # Separar o quê? Sem categoria no resultado, quem resolve é a IA.
        return None
    raw = {"grafico": novo, "grafico_de": origem.pk}
    if indice is not None:
        raw["grafico_de_consulta"] = indice
    return _Decisao(
        decision=AIReply.Decision.CONVERSATION,
        reply=ajuste_grafico.descrever(ajuste, len(linhas), novo.get("grupo") or ""),
        rule="ajuste_de_grafico",
        raw=raw,
    )


def foi_interrompida(message) -> bool:
    """A pessoa apertou parar enquanto isto rodava.

    Lido do banco a cada etapa porque o worker está em OUTRO processo: o
    clique chega pela API, que só escreve o status. É de propósito que a
    conferência seja uma consulta barata por etapa, e não um sinal — o que
    se quer evitar é a chamada seguinte ao modelo, que custa mil vezes mais
    do que este SELECT.
    """
    atual = Message.objects.filter(pk=message.pk).values_list("status", flat=True).first()
    return atual == Message.Status.CANCELLED


def _interrompida() -> _Decisao:
    """Sem texto de resposta: quem parou não quer ler nada.

    O AIReply mesmo assim é gravado, com as chamadas que já tinham sido
    feitas e o custo delas. Pergunta interrompida que sumisse da auditoria
    faria o `bi_report` mentir sobre o gasto do mês.
    """
    return _Decisao(
        decision=AIReply.Decision.CANCELLED,
        reply="",
        rule="interrompida_pelo_usuario",
        message_status=Message.Status.CANCELLED,
    )


def _processar(message, provider, executor, catalog, auditoria) -> _Decisao:
    if foi_interrompida(message):
        # Parada enquanto esperava na fila: nada foi chamado, nada foi gasto.
        return _interrompida()

    regra = apply_rules(message.content, catalog)
    if regra is not None and regra.rule == "mensagem_sem_pergunta" and (
        _responde_a_um_pedido_de_detalhe(message) or _tem_conversa_antes(message)
    ):
        # "2026", "3000": sem letra nenhuma, mas é a resposta ao "de qual
        # ano?" que o Jarvis acabou de perguntar. Recusar como mensagem
        # inválida foi o que aconteceu em produção (2026-09-21).
        # E "?" no meio de uma conversa quer dizer "cadê?": em 2026-09-23 o
        # Jarvis prometeu um gráfico, não fez, e ao "?" respondeu com o texto
        # de "não entendi a pergunta". Com conversa antes, quem lê é a IA.
        regra = None
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

    # E o teto do dia, desta pessoa. Vem logo depois do teto do mês e antes
    # de tudo que custa: quem estourou a cota não gasta um centavo para
    # descobrir isso. O aviso diz o número e diz quando volta.
    cota = limites.situacao(message.conversation.user)
    if cota["excedeu"]:
        janela = cota[cota["motivo"]]
        logger.info("Cota %s atingida por %s", cota["motivo"], message.conversation.user)
        # O texto não diz o número: a aba de limites também não diz, e duas
        # telas do mesmo produto não podem discordar sobre o que a pessoa
        # pode saber. A auditoria registra os dois, para quem administra.
        texto = canned.LIMITE_DIARIO if cota["motivo"] == "dia" else canned.LIMITE_SEMANAL
        return _Decisao(
            decision=AIReply.Decision.FAILED,
            reply=texto,
            rule="limite_diario_da_pessoa",
            raw={"janela": cota["motivo"], "limite": janela["limite"], "usadas": janela["usadas"]},
            message_status=Message.Status.FAILED,
        )

    historico = _historico(message)

    # Crítica à resposta anterior ("que coisa feia!!", com ou sem print): a
    # versão corrigida sai agora, sem a pessoa pedir de novo (conversa 22).
    critica = autocritica.e_critica(message.content) and _consulta_anterior(message) is not None
    nota_da_critica = autocritica.NOTA_DA_CRITICA if critica else ""
    if critica:
        auditoria.extras["critica_da_resposta_anterior"] = True

    if message.anexo_tipo == Message.Anexo.IMAGEM:
        # Imagem é outro caminho, com um décimo do custo (ADR-0024) — a menos
        # que o pedido precise do banco; aí ela vira pergunta ou planilha e
        # o caminho normal segue daqui.
        decisao = _ler_imagem(message, provider, auditoria, historico, critica=critica)
        if decisao is not None:
            return decisao
    elif not message.anexo_tipo:
        _herdar_planilha_da_conversa(message, auditoria)

    # A planilha da conversa (enviada agora, herdada ou vinda de um print)
    # vira `anexo.<aba>` para as consultas desta resposta (ADR-0031).
    executor = _preparar_planilha(message, executor, auditoria)

    plano = provider.plan(
        PlanRequest(
            question=_pergunta(message),
            history=historico,
            # Só a FORMA da planilha sobe ao modelo; o conteúdo fica aqui.
            planilha=_planilha(message),
            autocritica_note=nota_da_critica,
        )
    )
    for tentativa in plano.tentativas:
        auditoria.chamada(AICall.Stage.PLAN, tentativa)
    auditoria.chamada(AICall.Stage.PLAN, plano.usage)

    if _pediu_o_documento_inteiro(plano):
        # O contexto vai recortado por tema (ADR-0015). Quando o recorte não
        # basta, a IA avisa em vez de inventar a regra que faltou — e diz qual
        # tema faltou: vai esse tema completo, não o documento inteiro (81 mil
        # tokens e US$ 0,17 por "PRECISO DA SEÇÃO: marketing", 2026-10-01). O
        # documento inteiro fica para quando não der para saber qual tema é.
        pedidas = secoes_do_pedido(plano.reason)
        logger.info("A IA pediu %s: %s", pedidas or "o documento inteiro", plano.reason)
        if not pedidas and _passou_do_teto(auditoria, "documento inteiro"):
            pedidas = tuple((plano.usage.request or {}).get("secoes") or ())
        plano = provider.plan(
            PlanRequest(
                question=_pergunta(message), history=historico, full_context=not pedidas,
                secoes_pedidas=pedidas, planilha=_planilha(message), autocritica_note=nota_da_critica,
            )
        )
        auditoria.chamada(AICall.Stage.FIX, plano.usage)

    if critica and plano.intent == Plan.Intent.CONVERSATION:
        # Mesmo avisado, o planejador só reconheceu o erro. Uma segunda
        # chance, dizendo isso; é o que "Faça então amigo!!" fez na mão.
        logger.info("Crítica à resposta anterior respondida com conversa; replanejando")
        plano = provider.plan(
            PlanRequest(
                question=_pergunta(message), history=historico, planilha=_planilha(message),
                autocritica_note=nota_da_critica + (
                    "\n\nVocê já respondeu a esta crítica só com conversa, e isso deixa a "
                    "pessoa sem a correção. Refaça a consulta e o gráfico agora."
                ),
            )
        )
        auditoria.chamada(AICall.Stage.SELF_CHECK, plano.usage)

    # O plano já foi pago quando voltou; o que a parada evita daqui para a
    # frente é a consulta ao banco e a redação (~US$ 0,015), e numa
    # investigação, as rodadas seguintes inteiras.
    if foi_interrompida(message):
        return _interrompida()

    if plano.entendimento and plano.intent in (Plan.Intent.ANSWER_WITH_DATA, Plan.Intent.INVESTIGATE):
        # A tela troca o "Pensando…" pelo que foi entendido: é a hora mais
        # barata de a pessoa perceber que o pedido foi mal lido (e parar).
        progresso.definir(message.pk, "Montando a consulta", etapa="entendi", entendimento=plano.entendimento)

    if plano.intent == Plan.Intent.CONVERSATION:
        return _conversa(plano, message, historico)

    if plano.intent == Plan.Intent.INVESTIGATE and plano.investigacao:
        return _investigar(plano, message, provider, executor, catalog, auditoria, historico)

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

    if plano.intent == Plan.Intent.ANSWER_WITH_DATA and plano.consultas:
        if len(plano.consultas) >= 2:
            # Várias entregas — e, com planilha, várias abas a preencher ou
            # várias abas novas de análise (ADR-0031).
            return _entregar_varias(plano, message, provider, executor, catalog, auditoria, historico)
        if not plano.sql:
            # Uma entrega só (ou planilha, que se preenche de uma consulta):
            # é o caminho comum.
            primeira = plano.consultas[0]
            plano = replace(plano, sql=primeira["sql"],
                            reference_query_id=primeira.get("reference_query_id") or plano.reference_query_id,
                            preenchimento=plano.preenchimento or primeira.get("preenchimento") or {},
                            aba_nova=plano.aba_nova or primeira.get("aba_nova") or "",
                            grafico_na_aba=plano.grafico_na_aba or primeira.get("grafico_na_aba") or "")

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

    if foi_interrompida(message):
        return _interrompida()

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
        diagnostico, plano_da_verificacao = (
            (None, plano) if _passou_do_teto(auditoria, "verificação do resultado vazio")
            else _verificar_o_vazio(message, provider, executor, catalog, auditoria, historico)
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

    if plano.seguimento == autocritica.MUDA_O_DADO:
        plano, resultado = _autocriticar(plano, resultado, message, provider, executor, catalog, auditoria, historico)
        if foi_interrompida(message):
            return _interrompida()

    tem_planilha = message.anexo_tipo == Message.Anexo.PLANILHA
    itens = _itens_da_planilha(plano) if tem_planilha else []
    alteracao = _Alteracao()
    if itens:
        # A planilha sai ANTES da redação: a resposta fala do arquivo com os
        # números da conferência, em vez de adivinhar (conversa 44).
        alteracao = _alterar_planilha(message, itens, executor, catalog, auditoria, {plano.sql: resultado})
        if foi_interrompida(message):
            return _interrompida()
        inteiro = alteracao.resultados.get(plano.sql)
        if resultado.truncated and inteiro is not None and not inteiro.truncated:
            # A consulta da resposta parou em 500; a da planilha veio inteira
            # (513 cadastros do Balcão Seguro). A resposta não diz "cortado"
            # do que não foi cortado (2026-10-01).
            resultado = inteiro
    if tem_planilha and plano.preenchimento:
        # A consulta pode ter trazido o país inteiro; a resposta fala do que
        # a pessoa pediu (produção, 2026-09-22: 34 representantes para uma
        # planilha de 3). O preenchimento usou a consulta completa.
        resultado = _so_as_linhas_da_planilha(resultado, plano, message)
    # Com planilha a alterar, o arquivo que importa é o da pessoa: a
    # redação não é instruída a mandar ao "Baixar Excel" (o botão do
    # resultado completo continua na tela, como segunda opção).
    plano_da_redacao = replace(plano, excel=False) if itens else plano
    texto, raw = _redigir(plano_da_redacao, resultado, message, provider, catalog, auditoria, historico,
                          nota_da_planilha=alteracao.relatorio)
    texto = _com_aviso(texto, raw)
    texto += _nota_de_truncamento(resultado, catalog.max_rows)
    if plano.ressalva_forecast:
        # Projeção de Sell Out ou Sell In: a orientação sobre o dashboard é
        # acrescentada aqui, sempre, em vez de depender do texto do modelo.
        texto += "\n\n" + canned.RESSALVA_DE_FORECAST
        raw["ressalva_forecast"] = True

    if tem_planilha:
        if plano.operacao_da_planilha:
            raw["operacao_da_planilha"] = plano.operacao_da_planilha
        if itens:
            texto += alteracao.texto
            raw.update(alteracao.registro)
            if plano.preenchimento:
                raw["preenchimento"] = plano.preenchimento
            if alteracao.relatorio:
                _tabelas_com_a_planilha_entregue(raw, message, [plano.preenchimento] if plano.preenchimento else [])
        elif not getattr(message, "planilha_da_conversa", False) and not _usa_a_planilha(plano):
            # A consulta respondeu, mas o modelo não disse como casar as
            # colunas: a resposta em texto vale, e a planilha volta vazia.
            # Com a planilha de uma mensagem anterior, ou com uma consulta
            # que analisou a própria planilha, a pergunta pode ser outra:
            # aí o aviso não cabe.
            texto +="\n\n---\n\n" + canned.PLANILHA_SEM_CASAMENTO

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

    # A resposta pode ter ficado pronta no mesmo instante do clique em parar.
    # Nesse caso ela é descartada: quem apertou parar não quer ler. O custo
    # já gasto continua indo para a auditoria, logo abaixo.
    if decisao.message_status != Message.Status.CANCELLED and foi_interrompida(message):
        decisao = _interrompida()

    reply = _gravar(message, catalog, auditoria, decisao)

    if reply.reply_text:
        deliver_reply(channel, message.conversation, reply.reply_text, in_reply_to=message)

    return reply
