"""CRM LINK: a chave que liga o médico entre todas as bases (ADR-0032).

No BI o médico é `UF + 7 dígitos`, sempre com nove caracteres: `MG0039273`
em `audit.medico.crm` e em `audit.rx_cadastro_mais_recente.crm_link`
(conferido no RDS em 2026-10-01: 133.337 de 133.337). O número sozinho não
identifica ninguém — o CRM 39273 existe em vários estados.

As bases do Marketing guardam o número de outros jeitos: só os dígitos
(`81305`), com zeros a mais ou a menos, com traço, ponto ou barra, às vezes
com a UF colada (`SP123456`, `123456/SP`, `CRM-SP 12345`). E a UF vem num
campo separado. Aqui tudo isso vira o mesmo CRM LINK.
"""

import re

UFS = frozenset({
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
    "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
})
DIGITOS_DO_CRM = 7
PREFIXO_DO_CREMERJ = "52"
# Acima disto não é CRM: é telefone, CPF ou lixo de digitação. Mesmo teto do
# normalizar_crm da planilha anexada (attachments/planilha.py).
MAX_DIGITOS_DO_CRM = 10

_UF_NO_TEXTO = re.compile(r"(?<![A-Z])(" + "|".join(sorted(UFS)) + r")(?![A-Z])")


def uf_valida(valor) -> str:
    """A UF em maiúsculas se for uma das 27; senão vazio."""
    texto = re.sub(r"[^A-Za-z]", "", str(valor or "")).upper()
    return texto if texto in UFS else ""


def numero_do_crm(valor) -> str:
    """Só os dígitos, sem zeros à esquerda ("0081305" → "81305")."""
    digitos = re.sub(r"\D", "", str(valor or ""))
    return digitos.lstrip("0") or ("0" if digitos else "")


def uf_no_crm(valor) -> str:
    """A UF escrita dentro do próprio campo do CRM ("CRM-SP 12345")."""
    achados = _UF_NO_TEXTO.findall(str(valor or "").upper().replace("CRM", " "))
    return achados[0] if len(set(achados)) == 1 else ""


def crm_link(numero, uf="") -> str:
    """UF + número com zeros à esquerda até 7 dígitos, ou vazio.

    A mesma regra do CRM de fora do banco em todo o Jarvis (planilha anexada,
    documento de referência): a UF escrita junto do número ("CRM-MG 12345")
    vale primeiro — é a do conselho —, e só sem ela vale a do campo separado,
    que pode ser a do endereço. Sem UF não há CRM LINK: número solto não
    identifica médico, e chutar a UF seria inventar."""
    digitos = numero_do_crm(numero)
    if not digitos or digitos == "0" or len(digitos) > MAX_DIGITOS_DO_CRM:
        return ""
    estado = uf_no_crm(numero) or uf_valida(uf)
    if not estado:
        return ""
    if estado == "RJ" and len(digitos) > DIGITOS_DO_CRM and digitos.startswith(PREFIXO_DO_CREMERJ):
        # "52.12345-6": o 52 é o código do CREMERJ, que o BI não guarda.
        # Tirá-lo recuperou 55 dos 90 CRMs longos do RJ (2026-10-01).
        digitos = digitos[len(PREFIXO_DO_CREMERJ):].lstrip("0") or "0"
    return estado + digitos.zfill(DIGITOS_DO_CRM)


# Profissional de saúde que não é médico: o número do conselho dele (CRO,
# CRMV, CRF) não é CRM, e virar CRM LINK faria um dentista de CRO PR 33262
# casar com o médico de CRM PR 33262 (Área Médica, 2026-10-01: ~100 dentistas
# e veterinários). Reconhecido pela especialidade ou pela profissão.
_CONSELHOS = (
    ("CRO", ("dentist", "odonto", "bucomaxilo")),
    ("CRMV", ("veterin",)),
    ("CRF", ("farmac", "balconist")),
)


def conselho(*descricoes) -> str:
    """CRM, salvo quando a especialidade ou a profissão dizem outro conselho."""
    texto = " ".join(str(d or "") for d in descricoes).lower()
    for sigla, pistas in _CONSELHOS:
        if any(p in texto for p in pistas):
            return sigla
    return "CRM"
