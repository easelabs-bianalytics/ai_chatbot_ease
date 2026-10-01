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

    A UF do campo próprio vale primeiro; se ele estiver vazio ou inválido,
    vale a que estiver escrita no campo do CRM. Sem UF não há CRM LINK —
    número solto não identifica médico, e chutar a UF seria inventar."""
    digitos = numero_do_crm(numero)
    if not digitos or digitos == "0":
        return ""
    estado = uf_valida(uf) or uf_no_crm(numero)
    if not estado:
        return ""
    return estado + digitos.zfill(DIGITOS_DO_CRM)
