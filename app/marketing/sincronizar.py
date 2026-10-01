"""A sincronização diária das bases do Marketing (ADR-0032).

Roda como task ECS agendada (EventBridge Scheduler, o padrão do `sync` do
Cockpit), uma vez por dia de madrugada. Cada fonte é independente: se o
ActiveCampaign cair, a Área Médica é atualizada mesmo assim, e a fonte que
falhou continua com os dados de ontem — com a falha registrada em
`marketing.sincronizacoes`, que é de onde o Jarvis diz de quando é o dado.

A conexão é a da role dona do schema (`jarvis_mkt_sync`), e só ela: a
aplicação web nunca escreve no banco de negócio (ADR-0002, ADR-0008).
"""

import json
import logging
import os
from pathlib import Path

import psycopg2

from marketing import carga

logger = logging.getLogger(__name__)

ESQUEMA = Path(__file__).resolve().parent / "esquema.sql"
# Marca no log de toda falha: é por ela que o alarme do CloudWatch avisa
# (metric filter no grupo /aws/ecs/cockpit-prod).
MARCA_DE_FALHA = "SINCRONIZACAO_MARKETING_FALHOU"
FONTES = ("area_medica", "email_mkt")


def conectar():
    """A conexão de escrita no schema `marketing`: MARKETING_DATABASE_URL ou
    os campos discretos MARKETING_DB_* (a convenção dos secrets da casa)."""
    url = os.environ.get("MARKETING_DATABASE_URL", "").strip()
    if url:
        return psycopg2.connect(url, connect_timeout=15)
    campos = {
        "host": os.environ.get("MARKETING_DB_HOST"), "port": os.environ.get("MARKETING_DB_PORT") or 5432,
        "dbname": os.environ.get("MARKETING_DB_NAME"), "user": os.environ.get("MARKETING_DB_USER"),
        "password": os.environ.get("MARKETING_DB_PASSWORD"), "sslmode": os.environ.get("MARKETING_DB_SSLMODE") or None,
    }
    if not campos["host"]:
        raise RuntimeError("banco do Marketing não configurado: defina MARKETING_DATABASE_URL ou MARKETING_DB_*")
    return psycopg2.connect(connect_timeout=15, **{k: v for k, v in campos.items() if v not in (None, "")})


def preparar(conexao) -> None:
    with conexao.cursor() as cursor:
        cursor.execute(ESQUEMA.read_text(encoding="utf-8"))
    conexao.commit()


def _registrar_inicio(conexao, fonte) -> int:
    with conexao.cursor() as cursor:
        cursor.execute(
            "INSERT INTO marketing.sincronizacoes (fonte, status) VALUES (%s, 'rodando') RETURNING id", (fonte,)
        )
        identificador = cursor.fetchone()[0]
    conexao.commit()
    return identificador


def _registrar_fim(conexao, identificador, status, linhas=None, erro="") -> None:
    with conexao.cursor() as cursor:
        cursor.execute(
            "UPDATE marketing.sincronizacoes SET terminada_em = now(), status = %s, linhas = %s, erro = %s "
            "WHERE id = %s",
            (status, json.dumps(linhas or {}), erro[:2000], identificador),
        )
    conexao.commit()


def _carregar(fonte, conexao, area_medica, email_mkt) -> dict:
    if fonte == "area_medica":
        return carga.gravar_area_medica(conexao, area_medica.usuarios())
    campos, listas, tags, campanhas = email_mkt.campos(), email_mkt.listas(), email_mkt.tags(), email_mkt.campanhas()
    return carga.gravar_email_mkt(conexao, email_mkt.contatos(), campos, listas, tags, campanhas)


def sincronizar(conexao, area_medica, email_mkt, fontes=FONTES) -> dict:
    """{fonte: {"status", "linhas" | "erro"}}. Cada fonte numa transação:
    tudo chega e é gravado, ou nada muda."""
    preparar(conexao)
    resultado = {}
    for fonte in fontes:
        identificador = _registrar_inicio(conexao, fonte)
        try:
            linhas = _carregar(fonte, conexao, area_medica, email_mkt)
            conexao.commit()
        except Exception as exc:  # noqa: BLE001 — a outra fonte segue; esta fica registrada
            conexao.rollback()
            erro = f"{type(exc).__name__}: {exc}"
            logger.error("%s fonte=%s erro=%s", MARCA_DE_FALHA, fonte, erro)
            _registrar_fim(conexao, identificador, "falhou", erro=erro)
            resultado[fonte] = {"status": "falhou", "erro": erro}
            continue
        _registrar_fim(conexao, identificador, "ok", linhas)
        logger.info("Marketing sincronizado: fonte=%s %s", fonte, linhas)
        resultado[fonte] = {"status": "ok", "linhas": linhas}
    return resultado
