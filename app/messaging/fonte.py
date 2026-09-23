"""De onde saiu uma resposta, no formato que as telas leem (FR da Fase 6).

Um lugar só para o chat web e o WhatsApp (ADR-0028): os dois mostram a
mesma resposta — blocos, gráfico, planilha, investigação —, cada um do seu
jeito.
"""

from datasource.models import QueryRun
from messaging.models import Message


def montar(resposta, mostrar_custo: bool = False):
    """De onde saiu a resposta: a consulta que rodou, a referência em que se
    baseou, quando e com quantas linhas (FR da Fase 6).

    É o que permite ao usuário confiar no número sem confiar na IA — e ao
    time de BI conferir uma resposta estranha sem abrir o Admin."""
    pergunta = resposta.in_reply_to
    reply = getattr(pergunta, "ai_reply", None) if pergunta is not None else None
    if reply is None:
        return None

    consultas = sorted(reply.query_runs.all(), key=lambda q: q.attempt)
    executada = next(
        (q for q in reversed(consultas) if q.status == QueryRun.Status.SUCCESS), None
    )
    fonte = {
        "decisao": reply.decision,
        "regra": reply.rule,
        "respondida_em": reply.created_at.isoformat(),
        "tentativas": len(consultas),
        "consulta": None,
    }
    if executada is not None:
        fonte["consulta"] = {
            "sql": executada.sql,
            "referencia": executada.reference_query_id,
            "linhas": executada.row_count,
            "cortada": executada.truncated,
            "duracao_ms": executada.duration_ms,
        }
        pedido = bool((reply.raw_response or {}).get("excel"))
        # Uma linha só é um número, e ele já está no texto da resposta: um
        # botão de planilha ali só promete algo que não acrescenta nada.
        # Com duas ou mais, a planilha é o jeito de levar o resultado inteiro,
        # mesmo quando a resposta é só texto. Pedido explícito sempre vence.
        fonte["excel"] = pedido or (executada.row_count or 0) > 1
        fonte["excel_pedido"] = pedido
        grafico = (reply.raw_response or {}).get("grafico")
        amostra = executada.result_sample or {}
        if grafico and amostra.get("rows"):
            # O gráfico é desenhado no navegador com os números da consulta.
            fonte["grafico"] = grafico
            fonte["dados"] = {"columns": amostra.get("columns", []), "rows": amostra["rows"]}
    origem = (reply.raw_response or {}).get("grafico_de")
    if origem and not fonte.get("grafico"):
        # Ajuste de gráfico (regra `ajuste_de_grafico`): a resposta não rodou
        # consulta nenhuma; os números vêm da que desenhou o gráfico original.
        anterior = Message.objects.filter(pk=origem).select_related("in_reply_to__ai_reply").first()
        anterior_reply = getattr(getattr(anterior, "in_reply_to", None), "ai_reply", None)
        consulta = (
            anterior_reply.query_runs.filter(status=QueryRun.Status.SUCCESS).order_by("-attempt").first()
            if anterior_reply
            else None
        )
        amostra = (consulta.result_sample or {}) if consulta else {}
        indice = (reply.raw_response or {}).get("grafico_de_consulta")
        if indice is not None and anterior_reply is not None:
            # O gráfico ajustado estava num bloco: os números são os do bloco.
            amostra = ((anterior_reply.raw_response or {}).get("dados_blocos") or {}).get(str(indice)) or {}
        if amostra.get("rows"):
            fonte["grafico"] = (reply.raw_response or {}).get("grafico")
            fonte["dados"] = {"columns": amostra.get("columns", []), "rows": amostra["rows"]}

    sugestoes = (reply.raw_response or {}).get("sugestoes")
    if sugestoes:
        fonte["sugestoes"] = sugestoes

    raw = reply.raw_response or {}
    if raw.get("blocos"):
        # Resposta em blocos (ADR-0025): a tela desenha na ordem, com os
        # dados de cada consulta citada. O gráfico solto dá lugar aos blocos.
        fonte["blocos"] = raw["blocos"]
        fonte["dados_blocos"] = raw.get("dados_blocos") or {}
        fonte.pop("grafico", None)
        fonte.pop("dados", None)
    if raw.get("entregas"):
        # Várias entregas (ADR-0026): o painel mostra a consulta de cada uma,
        # no mesmo formato da investigação. A planilha sairia de uma só.
        fonte["investigacao"] = [
            {"rodada": 1, "hipotese": e.get("titulo", ""), "sql": e.get("sql", ""),
             "linhas": e.get("linhas"), "erro": e.get("erro", "")}
            for e in raw["entregas"]
        ]
        fonte["excel"] = False
    if raw.get("investigacao"):
        # Uma investigação roda várias consultas: o painel de fonte mostra
        # todas, cada uma com a hipótese que testou. A planilha de download
        # sairia de uma só delas, escolhida ao acaso — melhor não oferecer.
        fonte["investigacao"] = raw["investigacao"]
        fonte["excel"] = False
    if mostrar_custo:
        fonte["custo_usd"] = float(reply.cost_estimate or 0)
        fonte["tokens"] = (reply.tokens_input or 0) + (reply.tokens_output or 0)
        fonte["tempo_ms"] = reply.latency_ms
    return fonte
