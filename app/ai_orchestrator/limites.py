"""Quantas perguntas cada pessoa pode fazer por dia.

O teto mensal (`budget.py`) protege a fatura da empresa; este protege a
fatura de um dia ruim — alguém preso num laço de tentativa e erro, ou uma
conta esquecida aberta. São coisas diferentes e as duas valem ao mesmo
tempo.

**Três perfis**, por pessoa:

- quem toca o produto não tem limite;
- quem usa com frequência tem um limite folgado;
- o restante do domínio tem um limite menor, que ainda cobre o uso normal.

São duas janelas: **por dia** e **por semana**. O dia e a semana são os de
São Paulo (`TIME_ZONE`), não os do UTC — quem pergunta às 22h de terça não
pode descobrir que já está na quarta. A semana é de calendário, começando na
segunda: "renova na segunda" é uma frase que a pessoa consegue prever.

**O que consome cota é pergunta respondida.** Não contam:

- `clarify` — o Jarvis é que pediu o detalhe; a pessoa ainda não teve
  resposta, e cobrar duas por uma pergunta que ela precisou repetir é
  punir o nosso pedido;
- `failed` — falha nossa ou do banco;
- `cancelled` — ela mesma interrompeu.

Trocar alguém de perfil é mexer nestas listas e subir a imagem. É de
propósito: a lista fica no código, versionada e visível em revisão, em vez
de numa tabela que alguém edita sem deixar rastro.
"""

import datetime

from django.utils import timezone

from ai_orchestrator.models import AIReply

# Time do produto: sem limite. O teto mensal continua valendo para todos.
SEM_LIMITE = frozenset({
    "rubens.filho@easelabs.com.br",
    "paulo.lima@easelabs.com.br",
    "natalia.miranda@easelabs.com.br",
    "gustavo@easelabs.com.br",
    "guilherme@easelabs.com.br",
    "fernando.franco@easelabs.com.br",
})

# Uso frequente: consultam o Jarvis como parte do trabalho do dia.
COM_MAIS_CONSULTAS = frozenset({
    "renato.avilla@easelabs.com.br",
    "ivan.junior@easelabs.com.br",
    "gabriel.bastos@easelabs.com.br",
    "juliana.goularte@easelabs.com.br",
})

# Por dia e por semana. O diário evita o susto — alguém preso num laço de
# tentativa e erro numa tarde. O semanal evita o gotejamento: sem ele, doze
# por dia durante sete dias viram oitenta e quatro, e o teto diário nunca
# encostaria em ninguém.
LIMITE_COM_MAIS_CONSULTAS = 12
LIMITE_PADRAO = 7
SEMANAL_COM_MAIS_CONSULTAS = 60
SEMANAL_PADRAO = 35

# Decisões que não descontam da cota (ver o cabeçalho).
NAO_CONTAM = (
    AIReply.Decision.CLARIFY,
    AIReply.Decision.FAILED,
    AIReply.Decision.CANCELLED,
)


def _identidades(user) -> set:
    """E-mail e usuário, em minúsculas.

    O login por código grava o e-mail nos dois campos, mas contas antigas
    (e as dos testes) têm só o `username` — comparar os dois evita que um
    cadastro meia-boca fique sem limite nenhum por acidente.
    """
    return {str(getattr(user, campo, "") or "").strip().lower() for campo in ("email", "username")} - {""}


def limite_de(user) -> tuple[int, int] | None:
    """(por dia, por semana), ou None para quem não tem limite."""
    identidades = _identidades(user)
    if identidades & SEM_LIMITE:
        return None
    if identidades & COM_MAIS_CONSULTAS:
        return LIMITE_COM_MAIS_CONSULTAS, SEMANAL_COM_MAIS_CONSULTAS
    return LIMITE_PADRAO, SEMANAL_PADRAO


def inicio_da_semana(hoje=None):
    """Segunda-feira desta semana, no fuso de São Paulo.

    Semana de calendário, e não os últimos sete dias: "renova na segunda" é
    uma frase que a pessoa entende e consegue prever. Janela deslizante é
    mais justa na teoria e impossível de explicar na prática.
    """
    hoje = hoje or timezone.localdate()
    return hoje - datetime.timedelta(days=hoje.weekday())


def _contar(user, desde) -> int:
    return (
        AIReply.objects.filter(
            message__conversation__user=user,
            created_at__date__gte=desde,
        )
        .exclude(decision__in=NAO_CONTAM)
        .count()
    )


def usadas_hoje(user) -> int:
    return _contar(user, timezone.localdate())


def usadas_na_semana(user) -> int:
    return _contar(user, inicio_da_semana())


def _janela(usadas: int, limite: int) -> dict:
    return {
        "limite": limite,
        "usadas": usadas,
        "restante": max(0, limite - usadas),
        "excedeu": usadas >= limite,
    }


def situacao(user) -> dict:
    """As duas janelas. `dia` e `semana` são None para quem não tem limite."""
    limites_da_pessoa = limite_de(user)
    if limites_da_pessoa is None:
        return {"dia": None, "semana": None, "excedeu": False, "motivo": ""}

    por_dia, por_semana = limites_da_pessoa
    dia = _janela(usadas_hoje(user), por_dia)
    semana = _janela(usadas_na_semana(user), por_semana)
    # O dia vem primeiro no motivo porque é o que volta mais cedo: dizer
    # "volta amanhã" quando na verdade só volta na segunda seria mentir.
    motivo = "dia" if dia["excedeu"] else ("semana" if semana["excedeu"] else "")
    return {"dia": dia, "semana": semana, "excedeu": bool(motivo), "motivo": motivo}


def excedeu(user) -> bool:
    """Conferido ANTES de qualquer chamada paga: quem estourou não gasta."""
    return situacao(user)["excedeu"]
