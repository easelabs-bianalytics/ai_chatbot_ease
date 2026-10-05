"""Planilha Excel com o resultado de uma consulta (ADR-0020).

A planilha sai direto do banco, sem passar pela IA: não custa token e não
tem como trazer número inventado. O que ela precisa é parecer um relatório
do time de BI — cabeçalho da marca, bordas, filtro, primeira linha
congelada, números e datas no formato certo — e dizer de onde veio, numa
aba de informações.
"""

import datetime
import io
import re


INDIGO = "5558D4"
CINZA_BORDA = "DDDFE6"
CINZA_ZEBRA = "F7F8FA"
CINZA_TEXTO = "5E6484"

# Código não é número: CNPJ, EAN e CRM perdem o zero à esquerda e viram
# notação científica se o Excel os tratar como número.
_COLUNA_DE_CODIGO = re.compile(r"(cnpj|cpf|ean|crm|cep|cod|telefone|telef|ddd|setor|anomes)", re.I)
_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATA_HORA = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")

_FONTE = "Calibri"


def _titulo_da_coluna(nome: str) -> str:
    """`total_und` → `Total und`: a planilha vai para quem não lê SQL."""
    texto = str(nome).replace("_", " ").strip()
    return texto[:1].upper() + texto[1:] if texto else texto


def _valor(coluna: str, valor):
    if valor is None:
        return None
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if _COLUNA_DE_CODIGO.search(coluna):
        if isinstance(valor, float) and valor.is_integer():
            valor = int(valor)
        return str(valor)
    if isinstance(valor, str):
        if _DATA.match(valor):
            try:
                return datetime.date.fromisoformat(valor)
            except ValueError:
                return valor
        if _DATA_HORA.match(valor):
            try:
                # O Excel não guarda fuso: fica a hora local de Brasília.
                return datetime.datetime.fromisoformat(valor).replace(tzinfo=None)
            except ValueError:
                return valor
    return valor


def _formato(valor) -> str | None:
    if isinstance(valor, datetime.datetime):
        return "dd/mm/yyyy hh:mm"
    if isinstance(valor, datetime.date):
        return "dd/mm/yyyy"
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return "#,##0"
    if isinstance(valor, float):
        return "#,##0.00" if not valor.is_integer() else "#,##0"
    return None


# Largura das colunas: medida nas primeiras linhas. Medir as 50.000 custava
# mais que o resto e não muda a largura de nada.
LINHAS_PARA_A_LARGURA = 500


def montar_planilha(colunas, linhas, info: dict) -> bytes:
    """Devolve o `.xlsx` pronto, com uma aba de dados.

    `info` vai para a aba "Informações": pergunta, momento, linhas, se foi
    cortado, referência e a consulta executada.

    Gravado com o `xlsxwriter`, linha a linha e com um formato pronto por
    tipo de valor. Em produção (2026-09-30) o `openpyxl`, que estilizava
    célula por célula, levava 162 s para a `trade_visita` inteira (35.658
    linhas × 52 colunas): o download do chat web caía no tempo do balanceador
    e o worker do WhatsApp ficava preso. A zebra é formatação condicional do
    próprio Excel, sem custo por linha."""
    aba = {"nome": "Dados (cortada)" if info.get("cortada") else "Dados", "colunas": colunas, "linhas": linhas}
    return montar_livro([aba], info)


def nome_de_aba(titulo: str, usados: set) -> str:
    """Nome de aba válido no Excel: até 31 caracteres, sem colchete, dois
    pontos, asterisco, interrogação ou barra, sem repetir (o Excel recusa
    duas abas com o mesmo nome)."""
    base = re.sub(r"[\[\]:*?/\\]", " ", str(titulo or "")).strip().strip("'") or "Dados"
    base = re.sub(r"\s+", " ", base)[:31].strip()
    nome, n = base, 2
    while nome.lower() in usados or nome.lower() == "informações":
        sufixo = f" ({n})"
        nome = base[: 31 - len(sufixo)].strip() + sufixo
        n += 1
    usados.add(nome.lower())
    return nome


def montar_livro(abas: list, info: dict) -> bytes:
    """Um `.xlsx` com uma aba por consulta, mais a aba "Informações".

    `abas`: [{"nome", "colunas", "linhas", e, se houver mais de uma,
    "linhas_total", "cortada", "sql", "referencia"}]. Pedido de "um Excel,
    um por aba" com duas entregas não tinha arquivo nenhum: a planilha só
    sabia ter uma aba de dados (conversa 71, 2026-10-05)."""
    import xlsxwriter

    saida = io.BytesIO()
    livro = xlsxwriter.Workbook(saida, {"in_memory": True, "strings_to_numbers": False,
                                         "strings_to_formulas": False, "strings_to_urls": False,
                                         "remove_timezone": True})
    base = {"font_name": _FONTE, "font_size": 10, "border": 1, "border_color": "#" + CINZA_BORDA}
    formatos = {
        None: livro.add_format(base),
        "dd/mm/yyyy": livro.add_format({**base, "num_format": "dd/mm/yyyy"}),
        "dd/mm/yyyy hh:mm": livro.add_format({**base, "num_format": "dd/mm/yyyy hh:mm"}),
        "#,##0": livro.add_format({**base, "num_format": "#,##0"}),
        "#,##0.00": livro.add_format({**base, "num_format": "#,##0.00"}),
    }
    cabecalho_fmt = livro.add_format({
        "font_name": _FONTE, "font_size": 11, "bold": True, "font_color": "#FFFFFF",
        "bg_color": "#" + INDIGO, "align": "center", "valign": "vcenter", "text_wrap": True,
        "border": 1, "border_color": "#" + CINZA_BORDA,
    })
    zebra = livro.add_format({"bg_color": "#" + CINZA_ZEBRA})

    usados = set()
    for aba in abas:
        nome = aba["nome"] if len(abas) == 1 else nome_de_aba(aba["nome"], usados)
        _escrever_aba(livro.add_worksheet(nome), aba["colunas"], aba["linhas"], formatos, cabecalho_fmt, zebra)
        aba["nome_final"] = nome

    # Cortada: o nome da aba já avisa, e o arquivo abre na aba "Informações",
    # onde está o aviso inteiro — quem só olhasse os dados não saberia.
    informacoes = _aba_de_informacoes(livro, info, abas if len(abas) > 1 else None)
    if info.get("cortada"):
        informacoes.activate()
    livro.close()
    return saida.getvalue()


def _escrever_aba(dados, colunas, linhas, formatos, cabecalho_fmt, zebra):
    cabecalho = [_titulo_da_coluna(c) for c in colunas]
    dados.write_row(0, 0, cabecalho, cabecalho_fmt)
    dados.set_row(0, 22)

    larguras = [len(t) for t in cabecalho]
    for n, linha in enumerate(linhas, start=1):
        for i, bruto in enumerate(linha):
            valor = _valor(colunas[i], bruto)
            formato = formatos.get(_formato(valor), formatos[None])
            if valor is None:
                dados.write_blank(n, i, None, formato)
            elif isinstance(valor, (datetime.date, datetime.datetime)):
                dados.write_datetime(n, i, valor, formato)
            elif isinstance(valor, (int, float)):
                dados.write_number(n, i, valor, formato)
            else:
                dados.write_string(n, i, str(valor), formato)
            if n <= LINHAS_PARA_A_LARGURA:
                texto = valor.strftime("%d/%m/%Y") if isinstance(valor, datetime.date) else str(valor or "")
                larguras[i] = max(larguras[i], len(texto))

    for i, largura in enumerate(larguras):
        dados.set_column(i, i, min(max(largura + 3, 10), 60))
    dados.freeze_panes(1, 0)
    if colunas:
        ultima = max(len(linhas), 1)
        dados.autofilter(0, 0, ultima, len(colunas) - 1)
        if linhas:
            dados.conditional_format(1, 0, len(linhas), len(colunas) - 1, {
                "type": "formula", "criteria": "=MOD(ROW(),2)=1", "format": zebra,
            })


def _aba_de_informacoes(livro, info: dict, abas=None):
    """Com várias abas de dados, cada uma ganha a sua linha de linhas e a
    sua consulta, pelo nome da aba."""
    aba = livro.add_worksheet("Informações")
    aba.set_column(0, 0, 24)
    aba.set_column(1, 1, 100)

    aba.write(0, 0, "Jarvis · Ease Labs", livro.add_format({"font_name": _FONTE, "bold": True, "font_size": 14,
                                                           "font_color": "#" + INDIGO}))
    aba.write(1, 0, "BI & Analytics — dados consultados em modo somente leitura na base de BI",
              livro.add_format({"font_name": _FONTE, "font_size": 10, "font_color": "#" + CINZA_TEXTO}))

    borda = {"border": 1, "border_color": "#" + CINZA_BORDA, "valign": "top", "font_size": 10}
    rotulo_fmt = livro.add_format({**borda, "font_name": _FONTE, "bold": True})
    valor_fmt = livro.add_format({**borda, "font_name": _FONTE, "text_wrap": True})
    sql_fmt = livro.add_format({**borda, "font_name": "Consolas", "text_wrap": True})
    campos = [
        ("Pergunta", info.get("pergunta", "")),
        ("Planilha gerada em", info.get("gerada_em", "")),
    ]
    if abas:
        campos.append(("Observação", info.get("observacao", "")))
        for dados in abas:
            linhas = dados.get("linhas_total", len(dados["linhas"]))
            aviso = " — cortada no limite" if dados.get("cortada") else ""
            campos.append((f"Aba {dados['nome_final']}", f"{linhas} linhas{aviso}"))
            campos.append((f"Consulta: {dados['nome_final']}"[:60], dados.get("sql", "")))
    else:
        campos += [
            ("Linhas", info.get("linhas", "")),
            ("Observação", info.get("observacao", "")),
            ("Referência usada", info.get("referencia") or "nenhuma (consulta escrita pela IA)"),
            ("Consulta executada", info.get("sql", "")),
        ]
    for n, (rotulo, valor) in enumerate(campos, start=3):
        aba.write_string(n, 0, rotulo, rotulo_fmt)
        consulta = rotulo == "Consulta executada" or rotulo.startswith("Consulta: ")
        formato = sql_fmt if consulta else valor_fmt
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            aba.write_number(n, 1, valor, formato)
        else:
            aba.write_string(n, 1, str(valor or ""), formato)
        if consulta:
            aba.set_row(n, min(15 * (str(valor or "").count("\n") + 1), 400))
    return aba
