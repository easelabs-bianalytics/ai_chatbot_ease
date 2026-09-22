"""Planilha enviada pelo usuário: ler a forma e preencher com dado do banco.

Duas operações, e a separação entre elas é a garantia da ADR-0010 dentro da
planilha:

- `ler_estrutura` produz o resumo que sobe ao modelo — cabeçalhos, tipos e
  algumas linhas de amostra. Nunca o conteúdo todo.
- `preencher` escreve nas células, com o resultado da consulta, casando pela
  coluna-chave que o modelo indicou. O modelo não dita valor nenhum.
"""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from attachments.limites import (
    EXTENSOES_DE_PLANILHA,
    LINHAS_DE_AMOSTRA,
    MAX_CARACTERES_DO_RESUMO,
    MAX_COLUNAS,
    MAX_LINHAS,
    AnexoRecusado,
)

DELIMITADORES = ",;\t|"
# Caracteres que fazem o Excel tratar o texto como fórmula. Valor de banco
# que comece com eles vira texto explícito: uma célula que executa algo é
# problema de segurança de quem abre o arquivo, não conveniência nossa.
INICIOS_DE_FORMULA = ("=", "+", "-", "@")


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo: str
    exemplos: tuple


@dataclass(frozen=True)
class Estrutura:
    """O que sabemos da planilha sem mandar o conteúdo para ninguém."""

    nome: str
    aba: str
    abas: tuple
    colunas: tuple
    linhas: int

    @property
    def resumo(self) -> str:
        """O texto que vai ao modelo, com teto de caracteres.

        Formato deliberadamente enxuto: cada coluna em uma linha, com tipo e
        até dois exemplos. Uma planilha de 40 colunas cabe em ~800 tokens.
        """
        partes = [f"Arquivo: {self.nome}"]
        if len(self.abas) > 1:
            partes.append(f"Abas: {', '.join(self.abas)} (lendo \"{self.aba}\")")
        cobertura = " (a amostra abaixo traz todas elas)" if self.linhas <= LINHAS_DE_AMOSTRA else ""
        partes.append(f"Linhas de dados: {self.linhas}{cobertura}")
        partes.append("Colunas (nome · tipo · exemplos):")
        for coluna in self.colunas:
            # Coluna de texto costuma ser a chave (rede, representante,
            # produto): vão as oito linhas de amostra, e numa planilha
            # pequena isso é a lista inteira. Número e data, dois exemplos
            # bastam para o formato. Achado de 2026-09-21: com dois, o modelo
            # filtrou a consulta por dois dos três representantes.
            quantos = LINHAS_DE_AMOSTRA if coluna.tipo == "texto" else 2
            exemplos = " | ".join(str(e) for e in coluna.exemplos[:quantos])
            partes.append(f"- {coluna.nome} · {coluna.tipo}" + (f" · {exemplos}" if exemplos else ""))
        texto = "\n".join(partes)
        if len(texto) > MAX_CARACTERES_DO_RESUMO:
            texto = texto[:MAX_CARACTERES_DO_RESUMO].rstrip() + "\n(resumo cortado no limite)"
        return texto


@dataclass(frozen=True)
class PedidoDePreenchimento:
    """O casamento que o modelo propôs entre a planilha e o resultado.

    Uma chave e VÁRIAS colunas: a planilha real pede PX, variação, unidades
    e market share lado a lado, e uma consulta traz todos de uma vez. Cada
    par em `colunas` é (cabeçalho na planilha, coluna no resultado).
    """

    coluna_chave: str
    chave_no_resultado: str
    colunas: tuple

    @classmethod
    def do_plano(cls, bruto: dict) -> "PedidoDePreenchimento":
        return cls(
            coluna_chave=bruto["coluna_chave"],
            chave_no_resultado=bruto["chave_no_resultado"],
            colunas=tuple((c["coluna_destino"], c["valor_no_resultado"]) for c in bruto["colunas"]),
        )


@dataclass(frozen=True)
class Preenchimento:
    dados: bytes
    nome: str
    preenchidas: int
    sem_correspondencia: int
    ambiguas: int
    total: int
    # Casadas por nome contido, não idêntico: (como está na planilha, como
    # está no banco). Vão listadas na resposta para a pessoa conferir.
    aproximadas: tuple = ()
    # Chaves da planilha que ficaram em branco, pelo nome — é o que permite
    # corrigir "Drogaria São Paulo" para "DPSP" sem caçar linha por linha.
    sem_correspondencia_nomes: tuple = ()


def normalizar(valor) -> str:
    """Chave de comparação: sem acento, sem caixa, sem espaço sobrando.

    "Pague Menos " e "pague menos" são a mesma rede; sem isto o
    preenchimento erraria em quase toda planilha real."""
    texto = "" if valor is None else str(valor)
    sem_acento = unicodedata.normalize("NFD", texto.casefold())
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento).strip()


def _tipo(valores) -> str:
    reais = [v for v in valores if v not in (None, "")]
    if not reais:
        return "vazia"
    if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in reais):
        return "número"
    if all(isinstance(v, (date, datetime)) for v in reais):
        return "data"
    return "texto"


def _e_csv(nome: str) -> bool:
    return Path(nome).suffix.lower() == ".csv"


def validar_nome(nome: str) -> None:
    extensao = Path(nome or "").suffix.lower()
    if extensao not in EXTENSOES_DE_PLANILHA:
        raise AnexoRecusado(
            "Formato não aceito. Envie .xlsx, .xlsm ou .csv — ou uma imagem (.png, .jpg)."
        )


def _linhas_do_csv(dados: bytes) -> list:
    try:
        texto = dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Planilha exportada do Excel no Windows costuma vir em latin-1, e
        # recusar por causa de um "ç" seria absurdo.
        texto = dados.decode("latin-1", errors="replace")
    amostra = texto[:4096]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=DELIMITADORES)
        delimitador = dialeto.delimiter
    except csv.Error:
        delimitador = ";" if amostra.count(";") > amostra.count(",") else ","
    leitor = csv.reader(io.StringIO(texto), delimiter=delimitador)
    linhas = []
    for linha in leitor:
        linhas.append(linha[:MAX_COLUNAS])
        if len(linhas) > MAX_LINHAS + 1:  # +1 pelo cabeçalho
            raise AnexoRecusado(
                f"A planilha tem mais de {MAX_LINHAS:,} linhas.".replace(",", ".")
                + " Envie um recorte — por produto, período ou rede."
            )
    return linhas


def _linhas_do_xlsx(dados: bytes) -> tuple:
    from openpyxl import load_workbook

    try:
        # read_only não carrega a planilha inteira na memória; data_only usa
        # o valor que o Excel gravou, sem avaliar fórmula nenhuma.
        livro = load_workbook(io.BytesIO(dados), read_only=True, data_only=True)
    except Exception as exc:
        raise AnexoRecusado("Não consegui abrir esse arquivo como planilha.") from exc

    try:
        aba = livro.worksheets[0]
        abas = tuple(livro.sheetnames)
        linhas = []
        for linha in aba.iter_rows(values_only=True):
            linhas.append(tuple(linha[:MAX_COLUNAS]))
            if len(linhas) > MAX_LINHAS + 1:
                raise AnexoRecusado(
                    f"A planilha tem mais de {MAX_LINHAS:,} linhas.".replace(",", ".")
                    + " Envie um recorte — por produto, período ou rede."
                )
        return linhas, aba.title, abas
    finally:
        livro.close()


def ler_estrutura(nome: str, dados: bytes) -> Estrutura:
    """Cabeçalhos, tipos e amostra — o que o modelo precisa para propor o
    casamento, e nada além disso."""
    validar_nome(nome)

    if _e_csv(nome):
        linhas, aba, abas = _linhas_do_csv(dados), "", ()
    else:
        linhas, aba, abas = _linhas_do_xlsx(dados)

    uteis = [l for l in linhas if any(v not in (None, "") for v in l)]
    if not uteis:
        raise AnexoRecusado("A planilha está vazia.")

    cabecalho = uteis[0]
    corpo = uteis[1:]
    colunas = []
    for indice, bruto in enumerate(cabecalho):
        rotulo = str(bruto).strip() if bruto not in (None, "") else f"coluna {indice + 1}"
        valores = [linha[indice] if indice < len(linha) else None for linha in corpo]
        amostra = [v for v in valores[:LINHAS_DE_AMOSTRA] if v not in (None, "")]
        colunas.append(Coluna(nome=rotulo, tipo=_tipo(valores), exemplos=tuple(amostra)))

    return Estrutura(
        nome=nome,
        aba=aba,
        abas=abas,
        colunas=tuple(colunas),
        linhas=len(corpo),
    )


def _para_celula(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, str) and valor[:1] in INICIOS_DE_FORMULA:
        return "'" + valor
    return valor


# Menor nome que pode casar por estar contido em outro. Abaixo disto, "SA"
# ou "RJ" casariam com meio banco.
MIN_CARACTERES_PARA_APROXIMAR = 4


def _palavras(chave_normalizada: str) -> frozenset:
    return frozenset(re.findall(r"[a-z0-9]+", chave_normalizada))


class _Casador:
    """Casa a chave da planilha com a chave do resultado. Custo zero de token.

    Duas regras, nesta ordem:

    1. **Idêntica** depois de normalizar (caixa, acento, espaço): "pague
       menos" e "PAGUE MENOS".
    2. **Contida, e só se for única**: as palavras de uma estão todas na
       outra — "Drogasil" em "RAIA DROGASIL", "Panvel" em "PANVEL FARMACIAS".
       Se duas redes do banco servirem ("Drogaria" está em várias), nenhuma
       serve: escolher uma seria inventar o número. Casadas assim são
       listadas na resposta para conferir.

    Chave repetida no RESULTADO nunca é preenchida, pelo mesmo motivo.
    """

    def __init__(self, colunas, linhas, pedido: PedidoDePreenchimento):
        nomes = [str(c) for c in colunas]
        faltando = [
            nome
            for nome in (pedido.chave_no_resultado, *(valor for _, valor in pedido.colunas))
            if nome not in nomes
        ]
        if faltando or not pedido.colunas:
            raise AnexoRecusado("O resultado da consulta não tem as colunas do preenchimento.")
        i_chave = nomes.index(pedido.chave_no_resultado)
        i_valores = [nomes.index(valor) for _, valor in pedido.colunas]

        # Por chave, a tupla de valores na ordem de `pedido.colunas`.
        self.valores, self.originais, self.repetidas = {}, {}, set()
        for linha in linhas:
            chave = normalizar(linha[i_chave])
            if chave in self.valores:
                self.repetidas.add(chave)
                continue
            self.valores[chave] = tuple(linha[i] for i in i_valores)
            self.originais[chave] = "" if linha[i_chave] is None else str(linha[i_chave])
        self._palavras = {chave: _palavras(chave) for chave in self.valores}

    def casar(self, bruto):
        """(situação, valor, nome no banco). Situação: exata, aproximada,
        ambigua ou sem."""
        chave = normalizar(bruto)
        if chave in self.repetidas:
            return "ambigua", None, ""
        if chave in self.valores:
            return "exata", self.valores[chave], self.originais[chave]

        minhas = _palavras(chave)
        if not minhas:
            return "sem", None, ""
        candidatas = [
            outra
            for outra, delas in self._palavras.items()
            if delas and (
                (minhas <= delas and len(chave) >= MIN_CARACTERES_PARA_APROXIMAR)
                or (delas <= minhas and len(outra) >= MIN_CARACTERES_PARA_APROXIMAR)
            )
        ]
        if len(candidatas) == 1 and candidatas[0] not in self.repetidas:
            return "aproximada", self.valores[candidatas[0]], self.originais[candidatas[0]]
        return "sem", None, ""


class _Contagem:
    def __init__(self):
        self.preenchidas = self.faltaram = self.ambiguas = self.total = 0
        self.aproximadas, self.sem_nomes = [], []

    def registrar(self, bruto, situacao, nome_no_banco) -> bool:
        """Conta e diz se a célula deve ser preenchida."""
        self.total += 1
        if situacao == "ambigua":
            self.ambiguas += 1
            return False
        if situacao == "sem":
            self.faltaram += 1
            self.sem_nomes.append(str(bruto).strip())
            return False
        if situacao == "aproximada":
            self.aproximadas.append((str(bruto).strip(), nome_no_banco))
        self.preenchidas += 1
        return True

    def resultado(self, dados, nome) -> "Preenchimento":
        return Preenchimento(
            dados=dados,
            nome=nome,
            preenchidas=self.preenchidas,
            sem_correspondencia=self.faltaram,
            ambiguas=self.ambiguas,
            total=self.total,
            aproximadas=tuple(self.aproximadas),
            sem_correspondencia_nomes=tuple(self.sem_nomes),
        )


def _indice_da_coluna(cabecalho, nome: str) -> int | None:
    alvo = normalizar(nome)
    for indice, bruto in enumerate(cabecalho):
        if normalizar(bruto) == alvo:
            return indice
    return None


def preencher(nome: str, dados: bytes, pedido: PedidoDePreenchimento, colunas, linhas) -> Preenchimento:
    """Devolve a planilha do usuário com as colunas de destino preenchidas.

    Mantém tudo o que já estava lá — outras colunas, ordem das linhas,
    formatação do xlsx. Cria a coluna de destino que não existir, porque é o
    caso comum: a pessoa manda a lista e pede o número.
    """
    casador = _Casador(colunas, linhas, pedido)
    if _e_csv(nome):
        return _preencher_csv(nome, dados, pedido, casador)
    return _preencher_xlsx(nome, dados, pedido, casador)


def _preencher_csv(nome, dados, pedido, casador) -> Preenchimento:
    linhas = _linhas_do_csv(dados)
    uteis = [l for l in linhas if any(v not in (None, "") for v in l)]
    cabecalho = list(uteis[0])
    i_chave = _indice_da_coluna(cabecalho, pedido.coluna_chave)
    if i_chave is None:
        raise AnexoRecusado(f'A planilha não tem a coluna "{pedido.coluna_chave}".')

    destinos = []
    for destino, _ in pedido.colunas:
        indice = _indice_da_coluna(cabecalho, destino)
        if indice is None:
            cabecalho.append(destino)
            indice = len(cabecalho) - 1
        destinos.append(indice)

    saida = [cabecalho]
    contagem = _Contagem()
    for linha in uteis[1:]:
        linha = list(linha) + [""] * (len(cabecalho) - len(linha))
        bruto = linha[i_chave]
        if bruto not in (None, ""):
            situacao, valores, no_banco = casador.casar(bruto)
            if contagem.registrar(bruto, situacao, no_banco):
                for indice, valor in zip(destinos, valores):
                    linha[indice] = "" if valor is None else str(valor)
        saida.append(linha)

    buffer = io.StringIO(newline="")
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    escritor.writerows(saida)
    return contagem.resultado(buffer.getvalue().encode("utf-8-sig"), nome)


def _preencher_xlsx(nome, dados, pedido, casador) -> Preenchimento:
    from openpyxl import load_workbook

    # Aqui NÃO é read_only: para escrever é preciso o modo normal. O limite
    # de 5 MiB e de linhas existe por causa deste momento.
    try:
        livro = load_workbook(io.BytesIO(dados))
    except Exception as exc:
        raise AnexoRecusado("Não consegui abrir esse arquivo como planilha.") from exc

    aba = livro.worksheets[0]
    linha_do_cabecalho = None
    for linha in aba.iter_rows(min_row=1, max_row=min(aba.max_row or 1, 20)):
        if any(c.value not in (None, "") for c in linha):
            linha_do_cabecalho = linha
            break
    if linha_do_cabecalho is None:
        raise AnexoRecusado("A planilha está vazia.")

    cabecalho = [c.value for c in linha_do_cabecalho]
    numero_do_cabecalho = linha_do_cabecalho[0].row
    i_chave = _indice_da_coluna(cabecalho, pedido.coluna_chave)
    if i_chave is None:
        raise AnexoRecusado(f'A planilha não tem a coluna "{pedido.coluna_chave}".')

    destinos = []
    for destino, _ in pedido.colunas:
        indice = _indice_da_coluna(cabecalho, destino)
        if indice is None:
            indice = len(cabecalho)
            cabecalho.append(destino)
            aba.cell(row=numero_do_cabecalho, column=indice + 1, value=destino)
        destinos.append(indice)

    contagem = _Contagem()
    for numero in range(numero_do_cabecalho + 1, (aba.max_row or 0) + 1):
        bruto = aba.cell(row=numero, column=i_chave + 1).value
        if bruto in (None, ""):
            continue
        situacao, valores, no_banco = casador.casar(bruto)
        if contagem.registrar(bruto, situacao, no_banco):
            for indice, valor in zip(destinos, valores):
                aba.cell(row=numero, column=indice + 1, value=_para_celula(valor))

    buffer = io.BytesIO()
    livro.save(buffer)
    livro.close()
    return contagem.resultado(buffer.getvalue(), nome)


# Linhas que a leitura de um print pode transcrever. Um print legível não
# passa disto; o teto só impede que um erro do modelo vire planilha gigante.
MAX_LINHAS_DO_PRINT = 300


def montar_de_tabela(colunas, linhas) -> bytes:
    """xlsx em memória a partir da tabela transcrita de um print (ADR-0024).

    É o que dá sentido a colar o print de uma tabela vazia: ela vira uma
    planilha como outra qualquer e segue o caminho do preenchimento — números
    do banco, arquivo para baixar. Nada vai para disco.
    """
    from openpyxl import Workbook

    cabecalho = [str(c).strip() for c in colunas if str(c or "").strip()][:MAX_COLUNAS]
    if not cabecalho:
        raise AnexoRecusado("Não encontrei uma tabela no print.")
    livro = Workbook()
    aba = livro.active
    aba.title = "Tabela do print"
    aba.append(cabecalho)
    for linha in list(linhas)[:MAX_LINHAS_DO_PRINT]:
        valores = [("" if v is None else str(v).strip()) or None for v in list(linha)[: len(cabecalho)]]
        if any(valores):
            aba.append(valores)
    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()


def linhas_das_chaves(nome: str, dados: bytes, pedido: PedidoDePreenchimento, colunas, linhas) -> list:
    """Só as linhas do resultado que correspondem às chaves da planilha.

    A consulta pode trazer o país inteiro — 34 representantes para uma
    planilha de 3, como aconteceu em produção em 2026-09-22. O preenchimento
    já acerta (casa por chave), mas a resposta em texto e a tabela na tela
    falavam de todo mundo. Aqui o resultado é reduzido ao que foi pedido,
    na ordem da planilha, antes de a redação ver qualquer coisa.
    """
    if _e_csv(nome):
        uteis = [l for l in _linhas_do_csv(dados) if any(v not in (None, "") for v in l)]
    else:
        brutas, _, _ = _linhas_do_xlsx(dados)
        uteis = [list(l) for l in brutas if any(v not in (None, "") for v in l)]
    if not uteis:
        return []

    i_chave = _indice_da_coluna(uteis[0], pedido.coluna_chave)
    if i_chave is None:
        return []

    casador = _Casador(colunas, linhas, pedido)
    por_chave = {}
    for linha in linhas:
        por_chave[normalizar(linha[list(colunas).index(pedido.chave_no_resultado)])] = linha

    escolhidas, vistas = [], set()
    for linha in uteis[1:]:
        bruto = linha[i_chave] if i_chave < len(linha) else None
        if bruto in (None, ""):
            continue
        situacao, _, no_banco = casador.casar(bruto)
        if situacao not in ("exata", "aproximada"):
            continue
        chave = normalizar(no_banco)
        if chave in vistas:
            continue
        vistas.add(chave)
        if chave in por_chave:
            escolhidas.append(por_chave[chave])
    return escolhidas
