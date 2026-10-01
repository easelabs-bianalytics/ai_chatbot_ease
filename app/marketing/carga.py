"""Do que as APIs devolvem às tabelas do schema `marketing` (ADR-0032).

Cada fonte é gravada numa transação só: apaga e regrava. `DELETE` e não
`TRUNCATE` de propósito — o `TRUNCATE` trava a tabela, e uma pergunta ao
Jarvis no meio da carga ficaria esperando; com `DELETE`, quem consulta
durante a carga continua vendo a versão anterior até o `COMMIT`.
"""

import json
import unicodedata
from datetime import date, datetime, timezone

from psycopg2.extras import execute_values

from marketing.crm import conselho, crm_link, numero_do_crm, uf_valida

# Campos do ActiveCampaign que viram coluna, pelo título (o id muda de conta
# para conta; o título é o que a equipe de Marketing reconhece). Em ordem de
# preferência: o primeiro preenchido vale.
CAMPOS = {
    "crm_numero": ("CRM", "Número de registro no Conselho"),
    "uf_conselho": ("UF do Conselho", "UF", "Estado de atuação"),
    "profissao": ("Qual sua profissão?",),
    "especialidade": ("Especialidade", "Qual sua especialidade?", "Especilidade"),
    "categoria": ("Categoria",),
    "potencial": ("Potencial",),
    "representante": ("Representante",),
    "ultima_visita": ("Última visita",),
    "ja_prescreve_cannabis": ("Já Prescreve Cannabis Medicinal?",),
    "ja_prescreve_ease": ("Já Prescreve Ease Labs?",),
    "participa_mais_alivio": ("Participa do Programa Mais Alívio?",),
    "tipo_visita": ("Gostaria de receber visita?", "Visita"),
    "cidade_estado": ("Cidade/Estado",),
    "estado_atuacao": ("Estado de atuação",),
}
# Nunca copiados: senha não é dado de negócio em lugar nenhum.
CAMPOS_FORA = frozenset({"senha", "usuario"})

TAG_MEDICO = "é-médico"
TAG_INATIVO = "Inativo"


def _sem_acento(texto) -> str:
    base = unicodedata.normalize("NFD", str(texto or "").strip().lower())
    return "".join(c for c in base if unicodedata.category(c) != "Mn")


def _data(valor):
    """Data do ActiveCampaign ou da Área Médica, ou None ("", None e o
    "0000-00-00" que o ActiveCampaign usa para "nunca")."""
    if not valor or str(valor).startswith("0000"):
        return None
    texto = str(valor).strip().replace(" ", "T", 1)
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def _inteiro(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _texto(valor):
    texto = " ".join(str(valor).split()) if valor not in (None, "") else ""
    return texto or None


# ------------------------------------------------------------------ Área Médica


def linhas_da_area_medica(usuarios, agora) -> list:
    linhas, vistos = [], set()
    for u in usuarios:
        email = _texto(u.get("email"))
        if not email or email.lower() in vistos:
            continue
        vistos.add(email.lower())
        do_conselho = conselho(u.get("especialidade"))
        linhas.append((
            email.lower(), _texto(u.get("nome")), _texto(u.get("telefone")), _texto(u.get("crm_cro")),
            uf_valida(u.get("uf")) or _texto(u.get("uf")), _texto(u.get("cidade")), _texto(u.get("especialidade")),
            _texto(u.get("tipo_visita_tecnica")), _data(u.get("data_cadastro")), _inteiro(u.get("quantidade_acessos")),
            numero_do_crm(u.get("crm_cro")) or None,
            (crm_link(u.get("crm_cro"), u.get("uf")) or None) if do_conselho == "CRM" else None, agora, do_conselho,
            _data(u.get("ultimo_acesso")),
        ))
    return linhas


COLUNAS_AREA_MEDICA = (
    "email", "nome", "telefone", "crm_cro", "uf", "cidade", "especialidade", "tipo_visita_tecnica",
    "data_cadastro", "quantidade_acessos", "crm_numero", "crm_link", "sincronizado_em", "conselho", "ultimo_acesso",
)


def gravar_area_medica(conexao, usuarios, agora=None, hoje=None) -> dict:
    agora = agora or datetime.now(timezone.utc)
    hoje = hoje or date.today()
    linhas = linhas_da_area_medica(usuarios, agora)
    with conexao.cursor() as cursor:
        cursor.execute("DELETE FROM marketing.area_medica_usuarios")
        execute_values(
            cursor,
            f"INSERT INTO marketing.area_medica_usuarios ({', '.join(COLUNAS_AREA_MEDICA)}) VALUES %s",
            linhas, page_size=1000,
        )
        execute_values(
            cursor,
            "INSERT INTO marketing.area_medica_acessos_diarios (data, email, crm_link, quantidade_acessos) "
            "VALUES %s ON CONFLICT (data, email) DO UPDATE SET quantidade_acessos = EXCLUDED.quantidade_acessos, "
            "crm_link = EXCLUDED.crm_link",
            [(hoje, l[0], l[11], l[9]) for l in linhas], page_size=1000,
        )
    return {"usuarios": len(linhas), "com_crm_link": sum(1 for l in linhas if l[11])}


# ------------------------------------------------------------------ Email MKT


def _por_contato(itens, chave="contact"):
    grupos = {}
    for item in itens or []:
        grupos.setdefault(str(item.get(chave)), []).append(item)
    return grupos


def linhas_do_email_mkt(dados, campos, tags, agora) -> list:
    titulos = {str(c["id"]): c.get("title") or "" for c in campos}
    nomes_das_tags = {str(t["id"]): t.get("tag") or "" for t in tags}
    valores = _por_contato(dados.get("fieldValues"))
    tags_do_contato = _por_contato(dados.get("contactTags"))
    linhas = []
    for contato in dados.get("contacts") or []:
        cid = str(contato["id"])
        por_titulo = {}
        for valor in valores.get(cid, []):
            titulo = titulos.get(str(valor.get("field")), "")
            if _sem_acento(titulo) in CAMPOS_FORA or not titulo:
                continue
            if _texto(valor.get("value")):
                por_titulo[titulo] = _texto(valor.get("value"))
        coluna = {}
        for nome, opcoes in CAMPOS.items():
            coluna[nome] = next((por_titulo[o] for o in opcoes if por_titulo.get(o)), None)
        marcadas = {nomes_das_tags.get(str(t.get("tag")), "") for t in tags_do_contato.get(cid, [])}
        nome = " ".join(p for p in (_texto(contato.get("firstName")), _texto(contato.get("lastName"))) if p) or None
        uf = uf_valida(coluna["uf_conselho"])
        do_conselho = conselho(coluna["profissao"], coluna["especialidade"])
        linhas.append((
            int(cid), (_texto(contato.get("email")) or "").lower() or None, nome, _texto(contato.get("phone")),
            _data(contato.get("cdate")), _data(contato.get("udate")),
            _data(contato.get("last_open_date")), _data(contato.get("last_click_date")),
            _inteiro(contato.get("bounced_hard")), _inteiro(contato.get("bounced_soft")),
            numero_do_crm(coluna["crm_numero"]) or None, uf or coluna["uf_conselho"],
            (crm_link(coluna["crm_numero"], uf) or None) if do_conselho == "CRM" else None,
            coluna["profissao"], coluna["especialidade"], coluna["categoria"], coluna["potencial"],
            coluna["representante"], _data(coluna["ultima_visita"]), coluna["ja_prescreve_cannabis"],
            coluna["ja_prescreve_ease"], coluna["participa_mais_alivio"], coluna["tipo_visita"],
            coluna["cidade_estado"], coluna["estado_atuacao"],
            TAG_MEDICO in marcadas, TAG_INATIVO in marcadas,
            json.dumps(por_titulo, ensure_ascii=False), agora, do_conselho,
        ))
    return linhas


COLUNAS_EMAIL = (
    "contato_id", "email", "nome", "telefone", "criado_em", "atualizado_em", "ultima_abertura", "ultimo_clique",
    "bounces_hard", "bounces_soft", "crm_numero", "uf_conselho", "crm_link", "profissao", "especialidade",
    "categoria", "potencial", "representante", "ultima_visita", "ja_prescreve_cannabis", "ja_prescreve_ease",
    "participa_mais_alivio", "tipo_visita", "cidade_estado", "estado_atuacao", "e_medico", "inativo", "campos",
    "sincronizado_em", "conselho",
)


def _substituir(cursor, tabela, colunas, linhas):
    cursor.execute(f"DELETE FROM marketing.{tabela}")
    if linhas:
        execute_values(cursor, f"INSERT INTO marketing.{tabela} ({', '.join(colunas)}) VALUES %s ON CONFLICT DO NOTHING",
                       linhas, page_size=1000)


def gravar_email_mkt(conexao, dados, campos, listas, tags, campanhas, agora=None) -> dict:
    agora = agora or datetime.now(timezone.utc)
    contatos = linhas_do_email_mkt(dados, campos, tags, agora)
    ids = {l[0] for l in contatos}
    listas_do_contato = [
        (int(i["contact"]), int(i["list"]), _inteiro(i.get("status")), str(i.get("status")) == "1",
         _data(i.get("sdate")), _data(i.get("udate")))
        for i in dados.get("contactLists") or [] if _inteiro(i.get("contact")) in ids
    ]
    tags_do_contato = [
        (int(i["contact"]), int(i["tag"]), _data(i.get("cdate")))
        for i in dados.get("contactTags") or [] if _inteiro(i.get("contact")) in ids
    ]
    with conexao.cursor() as cursor:
        _substituir(cursor, "email_contatos", COLUNAS_EMAIL, contatos)
        _substituir(cursor, "email_listas", ("lista_id", "nome", "criada_em"),
                    [(int(l["id"]), _texto(l.get("name")), _data(l.get("cdate"))) for l in listas])
        _substituir(cursor, "email_listas_do_contato",
                    ("contato_id", "lista_id", "status", "inscrito", "inscrito_em", "atualizado_em"), listas_do_contato)
        _substituir(cursor, "email_tags", ("tag_id", "tag", "contatos"),
                    [(int(t["id"]), _texto(t.get("tag")), _inteiro(t.get("subscriber_count"))) for t in tags])
        _substituir(cursor, "email_tags_do_contato", ("contato_id", "tag_id", "aplicada_em"), tags_do_contato)
        _substituir(cursor, "email_campanhas", (
            "campanha_id", "nome", "tipo", "status", "enviada_em", "enviados", "aberturas", "aberturas_unicas",
            "cliques", "cliques_unicos", "descadastros", "bounces_hard", "bounces_soft", "automacao_id",
        ), [
            (int(c["id"]), _texto(c.get("name")), _texto(c.get("type")), _inteiro(c.get("status")), _data(c.get("sdate")),
             _inteiro(c.get("send_amt")), _inteiro(c.get("opens")), _inteiro(c.get("uniqueopens")),
             _inteiro(c.get("linkclicks")), _inteiro(c.get("uniquelinkclicks")), _inteiro(c.get("unsubscribes")),
             _inteiro(c.get("hardbounces")), _inteiro(c.get("softbounces")), _inteiro(c.get("automation")))
            for c in campanhas
        ])
    return {
        "contatos": len(contatos), "com_crm_link": sum(1 for l in contatos if l[12]),
        "listas_do_contato": len(listas_do_contato), "tags_do_contato": len(tags_do_contato),
        "campanhas": len(campanhas),
    }

