"""Planilha enviada pelo usuário: ler, perfilar e alterar (ADR-0024, ADR-0031).

A separação entre ler e escrever é a garantia da ADR-0010 dentro da
planilha:

- `ler_estrutura` perfila a pasta de trabalho sem modelo nenhum: onde está o
  cabeçalho, o tipo de cada coluna, quanto dela está preenchido, qual serve
  de chave, onde há fórmula. O RESUMO disso sobe ao modelo; as linhas ficam
  em `Pagina.registros`, e de lá vão ao banco como a tabela `anexo.<aba>`
  (`anexo_sql.py`) — nunca ao modelo.
- `preencher`, `adicionar_aba` e `anotar` escrevem com o resultado da
  consulta. O modelo não dita valor nenhum: ele diz qual coluna do resultado
  vai para qual coluna da planilha, e por quê.
"""

import csv
import io
import math
import re
import unicodedata
from copy import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from datasource.colunas import FORMATO_PERCENTUAL, e_percentual

from attachments.limites import (
    EXTENSOES_DE_PLANILHA,
    LINHAS_DE_AMOSTRA,
    CARACTERES_POR_ABA_A_MAIS,
    MAX_CARACTERES_DO_RESUMO,
    MAX_CARACTERES_DO_RESUMO_TOTAL,
    MAX_COLUNAS,
    MAX_LINHAS,
    AnexoRecusado,
)

DELIMITADORES = ",;\t|"
# Caracteres que fazem o Excel tratar o texto como fórmula. Valor de banco
# que comece com eles vira texto explícito: uma célula que executa algo é
# problema de segurança de quem abre o arquivo, não conveniência nossa.
INICIOS_DE_FORMULA = ("=", "+", "-", "@")


SCHEMA_DO_ANEXO = "anexo"
# Coluna que toda tabela `anexo.<aba>` traz: o número da linha no Excel (ou
# do registro no CSV). É por ela que o resultado volta à linha certa — sem
# casar nome com nome, sem ambiguidade.
COLUNA_DA_LINHA = "_linha"


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo: str
    exemplos: tuple
    # Perfil (ADR-0031): o nome dela no SQL, a posição na linha (0 = coluna
    # A), quantas linhas têm valor, quantos valores diferentes e quantas
    # células são fórmula. É o que deixa o modelo saber qual coluna é chave,
    # qual está vazia para preencher e qual é calculada — sem ver os dados.
    nome_sql: str = ""
    indice: int = 0
    preenchidas: int = 0
    distintas: int = 0
    formulas: int = 0
    # A fórmula da primeira linha calculada ("=$K$40*H2"): numa planilha de
    # racional, o porquê de cada número está nela, e não no valor.
    formula: str = ""
    # Textos numa coluna de número ("-", "Neo"): no SQL viram NULL.
    intrusos: tuple = ()

    @property
    def letra(self) -> str:
        from openpyxl.utils import get_column_letter

        return get_column_letter(self.indice + 1)


# Teto de cada exemplo no resumo. Um comentário de visita de 900 caracteres
# como "exemplo" comia o resumo inteiro e as colunas seguintes sumiam
# (Painel Médico, 2026-10-01).
MAX_CARACTERES_DO_EXEMPLO = 40
MAX_CARACTERES_DA_FORMULA = 90


def _curto(valor, teto: int = MAX_CARACTERES_DO_EXEMPLO) -> str:
    if isinstance(valor, float) and abs(valor) >= 10_000:
        texto = str(round(valor))
    elif isinstance(valor, float):
        texto = f"{valor:.6g}"
    elif isinstance(valor, datetime) and valor.time() == datetime.min.time():
        texto = valor.date().isoformat()
    else:
        texto = " ".join(str(valor).split())
    return texto if len(texto) <= teto else texto[: teto - 1].rstrip() + "…"


@dataclass(frozen=True)
class Pagina:
    """Uma aba da planilha: o cabeçalho, o perfil das colunas e as linhas."""

    nome: str
    colunas: tuple
    linhas: int
    # Colunas além de MAX_COLUNAS: não são lidas. Antes sumiam sem aviso
    # (2026-09-25); agora o resumo manda dizer quais ficaram de fora.
    colunas_de_fora: int = 0
    nome_sql: str = ""
    # Número da linha do cabeçalho no Excel. Planilha real costuma ter título
    # nas primeiras linhas ("Painel Médico - Simone"), e o cabeçalho vem
    # depois.
    linha_do_cabecalho: int = 1
    # As linhas de dados: ((número da linha, (valor de cada coluna, na ordem
    # de `colunas`)), ...). Vão ao banco como `anexo.<nome_sql>`; ao modelo,
    # nunca.
    registros: tuple = field(default=(), repr=False, compare=False)
    # O que está na aba e não é a tabela principal: totais, blocos de
    # parâmetros, notas ((coordenada, valor), ...). Planilha de racional tem
    # a tabela em cima e as premissas embaixo (Metas_FV: meta do trimestre
    # por SKU em K40, pesos em I64) — sem isso, o modelo via 65 "linhas" onde
    # há 32 representantes.
    fora_da_tabela: tuple = field(default=(), repr=False, compare=False)
    # Todas as células preenchidas: ((linha, letra, valor, fórmula), ...).
    # Viram `anexo.<aba>_celulas`, de onde o modelo lê qualquer parâmetro
    # pela coordenada.
    celulas: tuple = field(default=(), repr=False, compare=False)
    comentarios: tuple = field(default=(), repr=False, compare=False)
    oculta: bool = False

    @property
    def tabela_sql(self) -> str:
        return f"{SCHEMA_DO_ANEXO}.{self.nome_sql}"

    @property
    def tabela_das_celulas(self) -> str:
        return f"{SCHEMA_DO_ANEXO}.{self.nome_sql}{SUFIXO_DAS_CELULAS}" if self.celulas else ""

    @property
    def ultima_linha(self) -> int:
        return self.registros[-1][0] if self.registros else self.linha_do_cabecalho

    def _descrever_coluna(self, coluna) -> str:
        inicio = f"- {coluna.letra} · {coluna.nome} → {coluna.nome_sql}"
        if coluna.tipo == "vazia" and coluna.formulas:
            # Arquivo gerado por sistema grava a fórmula sem o valor: a
            # coluna parece vazia, mas preenchê-la apagaria o cálculo.
            return (
                f"{inicio} · fórmula em {coluna.formulas} linhas (coluna calculada, sem o valor gravado "
                f"no arquivo; não preencher) · {_curto(coluna.formula, MAX_CARACTERES_DA_FORMULA)}"
            )
        if coluna.tipo == "vazia":
            return f"{inicio} · vazia (0 de {self.linhas})"
        chave = (
            coluna.tipo == "texto" and coluna.preenchidas == self.linhas
            and coluna.distintas == coluna.preenchidas and self.linhas > 1
        )
        if chave:
            preenchimento = f"{coluna.preenchidas} de {self.linhas}, todas diferentes (serve de chave)"
        else:
            preenchimento = f"{coluna.preenchidas} de {self.linhas}, {coluna.distintas} diferentes"
        texto = f"{inicio} · {coluna.tipo} · {preenchimento}"
        if coluna.intrusos:
            texto += " · com texto em algumas (" + ", ".join(_curto(v, 15) for v in coluna.intrusos[:3]) + "; no SQL, NULL)"
        if coluna.formulas:
            texto += (
                f" · calculada em {coluna.formulas} linhas: "
                f"{_curto(coluna.formula, MAX_CARACTERES_DA_FORMULA)}"
            )
        # Coluna de texto costuma ser a chave (rede, representante, produto):
        # vão as oito linhas de amostra, e numa planilha pequena isso é a
        # lista inteira. Número e data, dois exemplos bastam para o formato.
        # Achado de 2026-09-21: com dois, o modelo filtrou a consulta por dois
        # dos três representantes.
        quantos = LINHAS_DE_AMOSTRA if coluna.tipo == "texto" else 2
        exemplos = " | ".join(_curto(e) for e in coluna.exemplos[:quantos])
        return texto + (f" · {exemplos}" if exemplos else "")

    def _descrever_fora(self, teto: int) -> str:
        if not self.fora_da_tabela or teto <= 0:
            return ""
        # Por linha: a que só tem número (os totais) vira uma frase curta; a
        # que tem rótulo vai inteira, porque é ela que diz o que os números
        # do bloco são ("ISOLADO 30 ML · R$ 758,5 · META 2T 8634").
        por_linha = {}
        for coordenada, valor in self.fora_da_tabela:
            numero = int(re.sub(r"^[A-Z]+", "", coordenada))
            por_linha.setdefault(numero, []).append((re.sub(r"\d+$", "", coordenada), valor))
        itens, total = [], 0
        for numero, celulas in por_linha.items():
            if not any(isinstance(v, str) for _, v in celulas):
                item = f"L{numero}: números em {celulas[0][0]}…{celulas[-1][0]} (totais?)"
            else:
                item = f"L{numero}: " + " ".join(f"{letra}={_curto(v, 28)}" for letra, v in celulas)
            if total + len(item) + 3 > teto:
                itens.append("…")
                break
            itens.append(item)
            total += len(item) + 3
        return (
            f"Fora da tabela principal (totais, premissas, outros blocos; os valores estão em "
            f"{self.tabela_das_celulas or 'células'}):\n" + "\n".join(itens)
        )

    def _descrever_comentarios(self, teto: int) -> str:
        if not self.comentarios or teto <= 0:
            return ""
        itens, total = [], 0
        for coordenada, texto in self.comentarios:
            item = f"{coordenada}: {_curto(texto, 110)}"
            if total + len(item) + 3 > teto:
                itens.append("…")
                break
            itens.append(item)
            total += len(item) + 3
        return "Comentários nas células: " + " · ".join(itens)

    def descrever(self, teto: int) -> str:
        cobertura = " (a amostra abaixo traz todas elas)" if self.linhas <= LINHAS_DE_AMOSTRA else ""
        faixa = (
            f"linhas {self.linha_do_cabecalho + 1} a {self.ultima_linha}"
            if self.registros else "sem linhas de dados"
        )
        partes = [
            f"Tabela SQL: {self.tabela_sql} — a tabela principal ({faixa}), com `{COLUNA_DA_LINHA}` = "
            f"número da linha no arquivo (o cabeçalho está na linha {self.linha_do_cabecalho})",
            f"Linhas de dados: {self.linhas}{cobertura}",
        ]
        if self.oculta:
            partes.insert(0, "(aba oculta no Excel)")
        if self.colunas_de_fora:
            partes.insert(0, (
                f"ATENÇÃO: a aba tem {len(self.colunas) + self.colunas_de_fora} colunas e só as primeiras "
                f"{len(self.colunas)} foram lidas; as outras {self.colunas_de_fora} não entram na resposta "
                "nem no preenchimento. Diga isso na resposta."
            ))
        partes.append("Colunas (letra · nome na planilha → coluna no SQL · tipo · preenchimento · fórmula · exemplos):")
        linhas_das_colunas = [self._descrever_coluna(coluna) for coluna in self.colunas]
        # Com o que está fora da tabela (premissas, totais), as colunas não
        # podem comer o teto inteiro: as que não cabem descritas vão só com
        # letra, nome e fórmula — o nome é o que mais diz.
        limite = int(teto * (0.55 if (self.fora_da_tabela or self.comentarios) else 0.95))
        usado = sum(len(p) + 1 for p in partes)
        for i, linha in enumerate(linhas_das_colunas):
            if usado + len(linha) + 1 > limite and i < len(linhas_das_colunas) - 1:
                resto = self.colunas[i:]
                partes.append(
                    f"Mais {len(resto)} colunas (letra · nome → SQL · fórmula): " + " | ".join(
                        f"{c.letra} {_curto(c.nome, 30)} → {c.nome_sql}"
                        + (f" ({_curto(c.formula, 40)})" if c.formula else "")
                        for c in resto
                    )
                )
                break
            partes.append(linha)
            usado += len(linha) + 1
        principal = "\n".join(partes)
        # O que sobra do teto vai para o que está fora da tabela e para os
        # comentários; a tabela principal vem primeiro, sempre.
        sobra = max(0, teto - len(principal) - 200)
        extras = [
            self._descrever_fora(int(sobra * 0.75)),
            self._descrever_comentarios(int(sobra * 0.25)),
        ]
        if self.celulas:
            extras.append(
                f"Todas as células desta aba: {self.tabela_das_celulas} "
                f"(`{COLUNA_DA_LINHA}`, coluna = letra, valor = texto, numero, formula)"
            )
        texto = "\n".join([principal, *(e for e in extras if e)])
        if len(texto) > teto:
            texto = texto[:teto].rstrip() + "\n(resumo cortado no limite)"
        return texto


SUFIXO_DAS_CELULAS = "_celulas"


@dataclass(frozen=True)
class Estrutura:
    """O que sabemos da planilha sem mandar o conteúdo para ninguém.

    Um arquivo do Excel quase nunca tem uma aba só: a pessoa manda a pasta
    de trabalho inteira e diz qual quer. Por isso `paginas` traz todas —
    antes só a primeira era lida, e o modelo respondia que "não consegue ver
    a Planilha1" para um arquivo que a tinha (caso real de 2026-09-22).
    """

    nome: str
    paginas: tuple
    # Pastas de trabalho externas que as fórmulas citam ("[1]Insumos!E8"):
    # o valor gravado é o que vale, e o resumo diz isso.
    externas: int = 0

    @property
    def abas(self) -> tuple:
        return tuple(p.nome for p in self.paginas if p.nome)

    @property
    def primeira(self) -> Pagina:
        return self.paginas[0]

    # Compatibilidade com quem só conhece a planilha de uma aba.
    @property
    def aba(self) -> str:
        return self.primeira.nome

    @property
    def colunas(self) -> tuple:
        return self.primeira.colunas

    @property
    def linhas(self) -> int:
        return self.primeira.linhas

    @property
    def teto(self) -> int:
        """O teto do resumo cresce com o número de abas: uma pasta de
        trabalho de oito abas com 475 caracteres cada chegava ao modelo com
        cada aba cortada no meio (Racional Metas, 2026-10-01)."""
        return min(MAX_CARACTERES_DO_RESUMO_TOTAL, MAX_CARACTERES_DO_RESUMO + CARACTERES_POR_ABA_A_MAIS * (len(self.paginas) - 1))

    @property
    def resumo(self) -> str:
        """O texto que vai ao modelo, com teto de caracteres.

        Cada coluna em uma linha, com letra, tipo, preenchimento, fórmula e
        exemplos curtos. Com várias abas, o teto é dividido entre elas — a
        aba pequena devolve o que não usou para as grandes —, e nenhuma
        empurra as últimas para fora do resumo.
        """
        cabecalho = [f"Arquivo: {self.nome}"]
        if self.externas:
            cabecalho.append(
                f"As fórmulas citam {self.externas} pasta(s) de trabalho externa(s); os valores gravados no "
                "arquivo são o que vale."
            )
        if len(self.paginas) == 1:
            topo = "\n".join(cabecalho) + "\n"
            return topo + self.primeira.descrever(self.teto - len(topo))

        cabecalho += [
            f"Abas ({len(self.paginas)}): {', '.join(self.abas)}",
            "A pergunta precisa dizer de qual aba se trata.",
        ]
        topo = "\n".join(cabecalho)
        disponivel = self.teto - len(topo) - 30 * len(self.paginas)
        completos = {i: p.descrever(10**6) for i, p in enumerate(self.paginas)}
        tetos = _dividir(disponivel, {i: len(t) for i, t in completos.items()})
        partes = [topo]
        for i, pagina in enumerate(self.paginas):
            texto = completos[i] if len(completos[i]) <= tetos[i] else pagina.descrever(tetos[i])
            partes.append(f'\n## Aba "{pagina.nome}"\n' + texto)
        return "\n".join(partes)


def _dividir(total: int, pedidos: dict) -> dict:
    """Divide `total` entre os pedidos: quem pede menos que a parte justa
    leva o que pediu, e a sobra vai para os outros."""
    tetos, restantes = {}, dict(pedidos)
    while restantes:
        justa = max(400, total // len(restantes))
        pequenos = {k: v for k, v in restantes.items() if v <= justa}
        if not pequenos:
            for k in restantes:
                tetos[k] = justa
            break
        for k, v in pequenos.items():
            tetos[k] = v
            total -= v
            del restantes[k]
    return tetos


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
    # Em qual aba escrever. Vazio = a primeira, que é o caso da planilha de
    # uma aba só e do CSV.
    aba: str = ""
    # Colunas JÁ existentes que o pedido manda reescrever (UPDATE explícito,
    # ADR-0031). Fora delas, célula com valor nunca é trocada: a base da
    # pessoa é preservada por padrão.
    sobrescrever: tuple = ()
    # (coluna de destino, por quê) — vai para a aba "Notas do Jarvis".
    justificativas: tuple = ()

    @property
    def por_linha(self) -> bool:
        """O resultado traz `_linha` (a consulta partiu de `anexo.<aba>`):
        cada valor volta à linha de onde veio, sem casar nome."""
        return normalizar(self.chave_no_resultado) == COLUNA_DA_LINHA

    @classmethod
    def do_plano(cls, bruto: dict) -> "PedidoDePreenchimento":
        colunas = bruto["colunas"]
        return cls(
            coluna_chave=bruto.get("coluna_chave") or bruto["chave_no_resultado"],
            chave_no_resultado=bruto["chave_no_resultado"],
            colunas=tuple((c["coluna_destino"], c["valor_no_resultado"]) for c in colunas),
            aba=(bruto.get("aba") or "").strip(),
            sobrescrever=tuple(c["coluna_destino"] for c in colunas if c.get("sobrescrever")),
            justificativas=tuple(
                (c["coluna_destino"], c["justificativa"]) for c in colunas if c.get("justificativa")
            ),
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
    # Casou, mas o banco devolveu tudo vazio para a linha. Antes contava como
    # preenchida: "228 de 230" com a coluna de representante em branco
    # (conversa 37, 2026-09-25).
    vazias_no_banco: int = 0
    # Quem são elas, pelo valor da coluna-chave. Com a consulta partindo de
    # `anexo.<aba>` (LEFT JOIN), o CRM que não existe no cadastro também
    # volta assim: linha presente, valor vazio.
    vazias_nomes: tuple = ()
    # Células que já tinham valor e foram mantidas (sem pedido de reescrever)
    # e as que foram reescritas por pedido explícito.
    preservadas: int = 0
    sobrescritas: int = 0
    # Nomes finais das colunas: as que nasceram agora e as que já existiam.
    criadas: tuple = ()
    atualizadas: tuple = ()
    aba: str = ""


def normalizar(valor) -> str:
    """Chave de comparação: sem acento, sem caixa, sem espaço sobrando.

    "Pague Menos " e "pague menos" são a mesma rede; sem isto o
    preenchimento erraria em quase toda planilha real."""
    texto = "" if valor is None else str(valor)
    sem_acento = unicodedata.normalize("NFD", texto.casefold())
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento).strip()


# Parte mínima dos valores que decide o tipo da coluna. Planilha de trabalho
# tem "-" no setor vago e "Neo" no nível do novato numa coluna de números
# (RACIONAL FATURAMENTO, 2026-10-01): por causa de duas células, a coluna
# inteira virava texto e a soma no SQL deixava de existir.
PARTE_QUE_DECIDE_O_TIPO = 0.8


def _e_numero(v) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _tipo(valores) -> str:
    reais = [v for v in valores if v not in (None, "")]
    if not reais:
        return "vazia"
    if sum(1 for v in reais if _e_numero(v)) >= PARTE_QUE_DECIDE_O_TIPO * len(reais):
        return "número"
    if sum(1 for v in reais if isinstance(v, (date, datetime))) >= PARTE_QUE_DECIDE_O_TIPO * len(reais):
        return "data"
    return "texto"


def _intrusos(valores, tipo: str) -> list:
    """Os textos numa coluna de número ou data ("-", "Neo"), sem repetir."""
    if tipo not in ("número", "data"):
        return []
    vistos = []
    for v in valores:
        if v in (None, "") or (_e_numero(v) if tipo == "número" else isinstance(v, (date, datetime))):
            continue
        if v not in vistos:
            vistos.append(v)
    return vistos


def _e_csv(nome: str) -> bool:
    return Path(nome).suffix.lower() == ".csv"


def validar_nome(nome: str) -> None:
    extensao = Path(nome or "").suffix.lower()
    if extensao not in EXTENSOES_DE_PLANILHA:
        raise AnexoRecusado(
            "Formato não aceito. Envie .xlsx, .xlsm ou .csv — ou uma imagem (.png, .jpg)."
        )


class _Linhas(list):
    """As linhas lidas, lembrando a largura original (antes do corte de
    MAX_COLUNAS)."""

    largura = 0


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
    linhas = _Linhas()
    for linha in leitor:
        linhas.largura = max(linhas.largura, len(linha))
        linhas.append(linha[:MAX_COLUNAS])
        if len(linhas) > MAX_LINHAS + 1:  # +1 pelo cabeçalho
            raise AnexoRecusado(
                f"A planilha tem mais de {MAX_LINHAS:,} linhas.".replace(",", ".")
                + " Envie um recorte — por produto, período ou rede."
            )
    return linhas


def _linhas_do_xlsx(dados: bytes, data_only: bool = True) -> tuple:
    from openpyxl import load_workbook

    try:
        # read_only não carrega a planilha inteira na memória; data_only usa
        # o valor que o Excel gravou, sem avaliar fórmula nenhuma. Sem ele,
        # a célula calculada vem como o texto da fórmula ("=B2*C2") — é
        # assim que o perfil descobre as colunas calculadas.
        livro = load_workbook(io.BytesIO(dados), read_only=True, data_only=data_only)
    except Exception as exc:
        raise AnexoRecusado("Não consegui abrir esse arquivo como planilha.") from exc

    try:
        total = 0
        abas = []
        for aba in livro.worksheets:
            linhas = _Linhas()
            for linha in aba.iter_rows(values_only=True):
                # Só conta a largura até a última célula preenchida: o Excel
                # costuma devolver colunas vazias à direita.
                preenchidas = [i for i, v in enumerate(linha) if v not in (None, "")]
                if preenchidas:
                    linhas.largura = max(linhas.largura, preenchidas[-1] + 1)
                linhas.append(tuple(linha[:MAX_COLUNAS]))
                total += 1
                # O limite é da pasta de trabalho inteira, não de cada aba:
                # é a memória do processo que está sendo protegida.
                if total > MAX_LINHAS + len(livro.worksheets):
                    raise AnexoRecusado(
                        f"A planilha tem mais de {MAX_LINHAS:,} linhas.".replace(",", ".")
                        + " Envie um recorte — por produto, período ou rede."
                    )
            abas.append((aba.title, linhas))
        return abas
    finally:
        livro.close()


def _vazio(valor) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


# Até onde o cabeçalho é procurado. Título, data de emissão e linha em branco
# antes da tabela cabem aqui com folga.
LINHAS_PARA_ACHAR_O_CABECALHO = 20


def indice_do_cabecalho(linhas) -> int | None:
    """Índice (na lista) da linha do cabeçalho, ou None se tudo está vazio.

    A primeira linha preenchida nem sempre é o cabeçalho: planilha de
    trabalho abre com título ("Painel Médico - Simone (setor 3000)") numa
    célula só. O cabeçalho é a primeira linha, entre as vinte primeiras, com
    pelo menos metade da largura da linha mais larga e com maioria de texto.
    Sem nenhuma assim, vale a primeira preenchida — o comportamento antigo.
    """
    candidatas = [
        (i, [v for v in linha if not _vazio(v)])
        for i, linha in enumerate(linhas[:LINHAS_PARA_ACHAR_O_CABECALHO])
    ]
    candidatas = [(i, cheias) for i, cheias in candidatas if cheias]
    if not candidatas:
        return None
    largura = max(len(cheias) for _, cheias in candidatas)
    for i, cheias in candidatas:
        textos = sum(1 for v in cheias if isinstance(v, str))
        if len(cheias) >= max(1, math.ceil(largura * 0.5)) and textos * 2 >= len(cheias):
            return i
    return candidatas[0][0]


def nome_sql(texto, reservados=()) -> str:
    """"Nome do médico" → `nome_do_medico`: sem acento, minúsculo, só letra,
    número e sublinhado. É como o modelo escreve a coluna no SQL."""
    base = normalizar(texto)
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    if not base:
        base = "coluna"
    if base[0].isdigit():
        base = f"c_{base}"
    candidato, n = base, 2
    while candidato in reservados:
        candidato, n = f"{base}_{n}", n + 1
    return candidato


def _valor_limpo(valor):
    """Texto sem espaço nas pontas; o resto como veio."""
    return valor.strip() if isinstance(valor, str) else valor


# Linhas do começo da tabela olhadas para escolher a coluna-âncora.
LINHAS_PARA_A_ANCORA = 20
# Linhas seguidas sem âncora que encerram a tabela principal.
LINHAS_SEM_ANCORA_PARA_ENCERRAR = 3


def fim_da_tabela(linhas, i_cabecalho: int) -> int:
    """Índice (na lista) logo depois da última linha da tabela principal.

    A âncora é a coluna mais preenchida no começo da tabela (o nome, o
    código). A tabela acaba quando três linhas seguidas não têm âncora: o
    que vem depois é total, nota ou outro bloco — na Metas_FV, os 32
    representantes, a linha de totais e, embaixo, as premissas por SKU.
    Uma linha solta sem âncora no meio (o "-" de um setor vago) não encerra
    nada."""
    cabecalho = linhas[i_cabecalho]
    inicio = linhas[i_cabecalho + 1: i_cabecalho + 1 + LINHAS_PARA_A_ANCORA]
    contagem = [
        (sum(1 for l in inicio if j < len(l) and not _vazio(l[j])), -j)
        for j, rotulo in enumerate(cabecalho)
        if not _vazio(rotulo)
    ]
    if not contagem:
        return len(linhas)
    ancora = -max(contagem)[1]

    def sem_ancora(i):
        if i >= len(linhas):
            return True
        linha = linhas[i]
        return ancora >= len(linha) or _vazio(linha[ancora])

    ultimo = i_cabecalho
    for i in range(i_cabecalho + 1, len(linhas)):
        if all(sem_ancora(i + k) for k in range(LINHAS_SEM_ANCORA_PARA_ENCERRAR)):
            break
        if any(not _vazio(v) for v in linhas[i]):
            ultimo = i
    return ultimo + 1


def _texto_da_formula(valor) -> str:
    """Fórmula como texto; a de matriz (ArrayFormula) também."""
    valor = getattr(valor, "text", valor)
    return valor if isinstance(valor, str) and valor.startswith("=") else ""


def _pagina(nome_da_aba: str, linhas, extras=None, nome_na_sql: str = "") -> Pagina | None:
    """Perfila uma aba. `extras` (só xlsx): as mesmas linhas com as fórmulas
    como texto, os comentários e se a aba está oculta."""
    extras = extras or {}
    formulas = extras.get("formulas")
    i_cabecalho = indice_do_cabecalho(linhas)
    if i_cabecalho is None:
        return None

    cabecalho = linhas[i_cabecalho]
    fim = fim_da_tabela(linhas, i_cabecalho)
    registros_brutos = [
        (numero, linha)
        for numero, linha in enumerate(linhas[i_cabecalho + 1:fim], start=i_cabecalho + 2)
        if any(not _vazio(v) for v in linha)
    ]
    colunas, nomes = [], {COLUNA_DA_LINHA}
    for indice, bruto in enumerate(cabecalho):
        valores = [_valor_limpo(linha[indice]) if indice < len(linha) else None for _, linha in registros_brutos]
        if _vazio(bruto) and all(_vazio(v) for v in valores):
            # Coluna sem cabeçalho e sem dado (a coluna A vazia de uma tabela
            # que começa em B): não é coluna, é margem.
            continue
        rotulo = str(bruto).strip() if not _vazio(bruto) else f"coluna {indice + 1}"
        cheios = [v for v in valores if not _vazio(v)]
        das_linhas = [
            _texto_da_formula(formulas[numero - 1][indice])
            for numero, _ in registros_brutos
            if formulas is not None and numero - 1 < len(formulas) and indice < len(formulas[numero - 1])
        ]
        com_formula = [f for f in das_linhas if f]
        sql = nome_sql(rotulo, nomes)
        nomes.add(sql)
        tipo = _tipo(valores)
        # Exemplos sem repetir: "MÉDICO | MÉDICO | MÉDICO" ocupava o espaço de
        # oito exemplos para dizer um.
        amostra = list(dict.fromkeys(v for v in cheios if tipo != "número" or _e_numero(v)))[:LINHAS_DE_AMOSTRA]
        colunas.append(Coluna(
            nome=rotulo, tipo=tipo, exemplos=tuple(amostra), nome_sql=sql, indice=indice,
            preenchidas=len(cheios), distintas=len({normalizar(v) for v in cheios}), formulas=len(com_formula),
            formula=com_formula[0] if com_formula else "", intrusos=tuple(_intrusos(valores, tipo)),
        ))
    if not colunas:
        return None

    registros = tuple(
        (numero, tuple(_valor_limpo(linha[c.indice]) if c.indice < len(linha) else None for c in colunas))
        for numero, linha in registros_brutos
    )
    de_fora = max(0, getattr(linhas, "largura", 0) - MAX_COLUNAS)
    return Pagina(
        nome=nome_da_aba, colunas=tuple(colunas), linhas=len(registros), colunas_de_fora=de_fora,
        nome_sql=nome_na_sql, linha_do_cabecalho=i_cabecalho + 1, registros=registros,
        fora_da_tabela=_fora_da_tabela(linhas, fim),
        celulas=_celulas(linhas, formulas) if formulas is not None else (),
        comentarios=tuple(extras.get("comentarios") or ()),
        oculta=bool(extras.get("oculta")),
    )


def _coordenada(i: int, j: int) -> str:
    from openpyxl.utils import get_column_letter

    return f"{get_column_letter(j + 1)}{i + 1}"


def _fora_da_tabela(linhas, fim: int) -> tuple:
    return tuple(
        (_coordenada(i, j), _valor_limpo(valor))
        for i in range(fim, len(linhas))
        for j, valor in enumerate(linhas[i])
        if not _vazio(valor)
    )


# Células que viram `anexo.<aba>_celulas`. Acima disso a aba é uma tabela
# grande, e a tabela principal já a cobre; a grade de células só pesaria.
MAX_CELULAS = 20_000


def _celulas(linhas, formulas) -> tuple:
    from openpyxl.utils import get_column_letter

    celulas = []
    for i, linha in enumerate(linhas):
        da_formula = formulas[i] if i < len(formulas) else ()
        for j in range(max(len(linha), len(da_formula))):
            valor = linha[j] if j < len(linha) else None
            formula = _texto_da_formula(da_formula[j]) if j < len(da_formula) else ""
            if _vazio(valor) and not formula:
                continue
            celulas.append((i + 1, get_column_letter(j + 1), _valor_limpo(valor), formula))
            if len(celulas) > MAX_CELULAS:
                return ()
    return tuple(celulas)


def _texto_do_comentario(texto: str) -> str:
    """Comentário em thread chega com um aviso do Excel na frente; o que
    importa é o que a pessoa escreveu."""
    texto = texto or ""
    for marca in ("\nComentário:\n", "\nComment:\n"):
        if marca in texto:
            texto = texto.split(marca, 1)[1]
    return " ".join(texto.split())


def _extras_do_xlsx(dados: bytes) -> tuple:
    """({aba: {"formulas", "comentarios", "oculta"}}, nº de pastas externas).

    Leitura no modo normal: é o que traz comentário, aba oculta e link
    externo. As fórmulas vêm como texto."""
    from openpyxl import load_workbook

    try:
        livro = load_workbook(io.BytesIO(dados), data_only=False, keep_links=True)
    except Exception as exc:
        raise AnexoRecusado("Não consegui abrir esse arquivo como planilha.") from exc
    extras = {}
    try:
        for aba in livro.worksheets:
            formulas = [tuple(l[:MAX_COLUNAS]) for l in aba.iter_rows(values_only=True)]
            comentarios = tuple(
                (celula.coordinate, _texto_do_comentario(celula.comment.text))
                for linha in aba.iter_rows() for celula in linha if celula.comment
            )
            extras[aba.title] = {"formulas": formulas, "comentarios": comentarios,
                                 "oculta": aba.sheet_state != "visible"}
        return extras, len(getattr(livro, "_external_links", ()) or ())
    finally:
        livro.close()


# O perfil roda a cada mensagem da conversa (a planilha é perfilada de novo
# em memória). Guardado por conteúdo, o segundo uso do mesmo arquivo é
# instantâneo; poucos, porque cada um segura as linhas da planilha.
_PERFIS: dict = {}
MAX_PERFIS_GUARDADOS = 4


def ler_estrutura(nome: str, dados: bytes) -> Estrutura:
    """O perfil de CADA aba, com as linhas guardadas para a tabela SQL.

    Nada aqui chama modelo: é determinístico e barato."""
    validar_nome(nome)
    import hashlib

    chave = (nome, hashlib.sha1(dados).hexdigest())
    if chave in _PERFIS:
        return _PERFIS[chave]

    if _e_csv(nome):
        brutas, extras, externas = [("", _linhas_do_csv(dados))], {}, 0
    else:
        brutas = _linhas_do_xlsx(dados)
        extras, externas = _extras_do_xlsx(dados)
    # Aba vazia não entra no resumo: ela ocuparia espaço para dizer nada, e
    # pasta de trabalho do Excel costuma carregar uma ou duas assim.
    paginas, nomes = [], set()
    for aba, linhas in brutas:
        base = "planilha" if not aba else nome_sql(aba)
        tabela = nome_sql(base, nomes | {n + SUFIXO_DAS_CELULAS for n in nomes})
        pagina = _pagina(aba, linhas, extras.get(aba), tabela)
        if pagina:
            nomes.add(tabela)
            paginas.append(pagina)
    if not paginas:
        raise AnexoRecusado("A planilha está vazia.")

    estrutura = Estrutura(nome=nome, paginas=tuple(paginas), externas=externas)
    if len(_PERFIS) >= MAX_PERFIS_GUARDADOS:
        _PERFIS.pop(next(iter(_PERFIS)))
    _PERFIS[chave] = estrutura
    return estrutura


def _para_celula(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, str):
        # "CAROLINE CARNIEL\t": o cadastro tem TAB e quebra de linha nas
        # pontas, e o `btrim` do modelo só tira espaço (2026-10-01).
        valor = valor.strip()
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


class _CasadorPorLinha:
    """O resultado traz `_linha`: cada valor volta à linha de onde veio.

    É o casamento da consulta que partiu de `anexo.<aba>` (ADR-0031). Nada
    de nome parecido nem de chave normalizada: a linha 17 do arquivo recebe
    o que a consulta calculou para a linha 17. Linha repetida no resultado
    (a consulta devolveu duas para a mesma linha) fica em branco, pelo mesmo
    motivo da chave repetida: escolher uma seria inventar."""

    def __init__(self, colunas, linhas, pedido: PedidoDePreenchimento):
        nomes = [normalizar(c) for c in colunas]
        origens = [normalizar(valor) for _, valor in pedido.colunas]
        faltando = [nome for nome in (COLUNA_DA_LINHA, *origens) if nome not in nomes]
        if faltando or not pedido.colunas:
            raise AnexoRecusado("O resultado da consulta não tem as colunas do preenchimento.")
        i_linha = nomes.index(COLUNA_DA_LINHA)
        i_valores = [nomes.index(origem) for origem in origens]
        self.valores, self.repetidas = {}, set()
        for linha in linhas:
            try:
                numero = int(linha[i_linha])
            except (TypeError, ValueError):
                continue
            if numero in self.valores:
                self.repetidas.add(numero)
                continue
            self.valores[numero] = tuple(linha[i] for i in i_valores)

    def casar(self, numero):
        if numero in self.repetidas:
            return "ambigua", None, ""
        if numero in self.valores:
            return "exata", self.valores[numero], ""
        return "sem", None, ""


class _Contagem:
    def __init__(self):
        self.preenchidas = self.faltaram = self.ambiguas = self.total = 0
        self.vazias = self.preservadas = self.sobrescritas = 0
        self.aproximadas, self.sem_nomes, self.vazias_nomes = [], [], []

    def registrar(self, bruto, situacao, nome_no_banco, valores=None) -> bool:
        """Conta e diz se a linha deve ser escrita."""
        self.total += 1
        if situacao == "ambigua":
            self.ambiguas += 1
            return False
        if situacao == "sem":
            self.faltaram += 1
            self.sem_nomes.append(str(bruto).strip())
            return False
        if valores is not None and all(_vazio(v) for v in valores):
            # Casou, e o banco não tinha nada para ela. Não é "preenchida".
            self.vazias += 1
            self.vazias_nomes.append(str(bruto).strip())
            return False
        if situacao == "aproximada":
            self.aproximadas.append((str(bruto).strip(), nome_no_banco))
        self.preenchidas += 1
        return True

    def resultado(self, dados, nome, criadas=(), atualizadas=(), aba="") -> "Preenchimento":
        return Preenchimento(
            dados=dados,
            nome=nome,
            preenchidas=self.preenchidas,
            sem_correspondencia=self.faltaram,
            ambiguas=self.ambiguas,
            total=self.total,
            aproximadas=tuple(self.aproximadas),
            sem_correspondencia_nomes=tuple(self.sem_nomes),
            vazias_no_banco=self.vazias,
            vazias_nomes=tuple(self.vazias_nomes),
            preservadas=self.preservadas,
            sobrescritas=self.sobrescritas,
            criadas=tuple(criadas),
            atualizadas=tuple(atualizadas),
            aba=aba,
        )


def _indice_da_coluna(cabecalho, nome: str) -> int | None:
    alvo = normalizar(nome)
    for indice, bruto in enumerate(cabecalho):
        if normalizar(bruto) == alvo:
            return indice
    return None


def _casador(colunas, linhas, pedido):
    return _CasadorPorLinha(colunas, linhas, pedido) if pedido.por_linha else _Casador(colunas, linhas, pedido)


def preencher(nome: str, dados: bytes, pedido: PedidoDePreenchimento, colunas, linhas) -> Preenchimento:
    """Devolve a planilha do usuário com as colunas de destino preenchidas.

    Mantém tudo o que já estava lá — outras colunas, ordem das linhas,
    fórmulas, formatação do xlsx. Cria a coluna de destino que não existir
    (ENRICHMENT, o caso comum: a pessoa manda a lista e pede o dado). Numa
    coluna que já existe (UPDATE), só escreve na célula vazia; reescrever
    célula com valor exige o pedido explícito (`sobrescrever`).
    """
    casador = _casador(colunas, linhas, pedido)
    if _e_csv(nome):
        return _preencher_csv(nome, dados, pedido, casador)
    return _preencher_xlsx(nome, dados, pedido, casador)


def _escrever(celula_atual, valor, pode_sobrescrever: bool, contagem) -> bool:
    """Decide se a célula recebe o valor. Célula com valor só muda com
    pedido explícito — e as duas situações ficam contadas."""
    if _vazio(valor):
        return False
    if _vazio(celula_atual):
        return True
    if pode_sobrescrever:
        contagem.sobrescritas += 1
        return True
    contagem.preservadas += 1
    return False


def _destinos(cabecalho, pedido):
    """(índice, criada?) de cada coluna de destino, na ordem do pedido.
    Coluna que não existe entra no fim do cabeçalho."""
    destinos, criadas, atualizadas = [], [], []
    largura = len(cabecalho)
    for destino, _ in pedido.colunas:
        indice = _indice_da_coluna(cabecalho[:largura], destino)
        if indice is None:
            indice = _indice_da_coluna(cabecalho, destino)
        if indice is None:
            cabecalho.append(destino)
            indice = len(cabecalho) - 1
            criadas.append(destino)
        elif indice < largura:
            atualizadas.append(str(cabecalho[indice]))
        destinos.append(indice)
    return destinos, criadas, atualizadas


def _pode_sobrescrever(pedido, cabecalho, indice) -> bool:
    return any(normalizar(nome) == normalizar(cabecalho[indice]) for nome in pedido.sobrescrever)


def _preencher_csv(nome, dados, pedido, casador) -> Preenchimento:
    linhas = _linhas_do_csv(dados)
    i_cabecalho = indice_do_cabecalho(linhas)
    if i_cabecalho is None:
        raise AnexoRecusado("A planilha está vazia.")
    cabecalho = list(linhas[i_cabecalho])
    i_chave = None if pedido.por_linha else _indice_da_coluna(cabecalho, pedido.coluna_chave)
    if i_chave is None and not pedido.por_linha:
        raise AnexoRecusado(f'A planilha não tem a coluna "{pedido.coluna_chave}".')
    i_rotulo = _indice_da_coluna(cabecalho, pedido.coluna_chave)

    destinos, criadas, atualizadas = _destinos(cabecalho, pedido)
    saida = [list(l) for l in linhas[:i_cabecalho]] + [cabecalho]
    contagem = _Contagem()
    for numero, linha in enumerate(linhas[i_cabecalho + 1:], start=i_cabecalho + 2):
        linha = list(linha) + [""] * (len(cabecalho) - len(linha))
        if pedido.por_linha:
            if all(_vazio(v) for v in linha):
                saida.append(linha)
                continue
            bruto = numero
            rotulo = linha[i_rotulo] if i_rotulo is not None and not _vazio(linha[i_rotulo]) else f"linha {numero}"
        else:
            bruto = linha[i_chave]
            rotulo = bruto
            if _vazio(bruto):
                saida.append(linha)
                continue
        situacao, valores, no_banco = casador.casar(bruto)
        if pedido.por_linha and situacao == "sem" and all(not _vazio(linha[i]) for i in destinos):
            saida.append(linha)
            continue
        if contagem.registrar(rotulo, situacao, no_banco, valores):
            for indice, valor in zip(destinos, valores):
                if _escrever(linha[indice], valor, _pode_sobrescrever(pedido, cabecalho, indice), contagem):
                    linha[indice] = "" if valor is None else str(valor)
        saida.append(linha)

    buffer = io.StringIO(newline="")
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    escritor.writerows(saida)
    return contagem.resultado(buffer.getvalue().encode("utf-8-sig"), nome, criadas, atualizadas)


def _aba_pedida(livro, nome_da_aba: str):
    """A aba que o plano indicou, casando pelo nome normalizado.

    "Planilha 3" e "Planilha3" são a mesma aba para quem escreveu a pergunta;
    exigir o nome exato faria a resposta falhar por um espaço. O nome da
    tabela SQL (`anexo.planilha_3`) também vale: é como o modelo a conhece."""
    if not nome_da_aba:
        return livro.worksheets[0]
    procurado = normalizar(nome_da_aba).replace(" ", "")
    for aba in livro.worksheets:
        if normalizar(aba.title).replace(" ", "") == procurado:
            return aba
    sem_schema = nome_sql(nome_da_aba.split(".", 1)[-1])
    for aba in livro.worksheets:
        if nome_sql(aba.title) == sem_schema:
            return aba
    if len(livro.worksheets) == 1:
        # Arquivo de uma aba só: o modelo pôs no campo o nome do ARQUIVO
        # ("Painel Médico - Simone (setor 3000)") e nada foi preenchido
        # (2026-10-01). Com uma aba, não há o que errar.
        return livro.worksheets[0]
    raise AnexoRecusado(
        f'A planilha não tem a aba "{nome_da_aba}". Abas: {", ".join(livro.sheetnames)}.'
    )


def _cabecalho_da_aba(aba):
    """(número da linha do cabeçalho, valores do cabeçalho), pela mesma
    regra da leitura: escrever num cabeçalho diferente do que o modelo viu
    poria o dado na coluna errada."""
    primeiras = [
        tuple(c.value for c in linha)
        for linha in aba.iter_rows(min_row=1, max_row=min(aba.max_row or 1, LINHAS_PARA_ACHAR_O_CABECALHO))
    ]
    indice = indice_do_cabecalho(primeiras)
    if indice is None:
        raise AnexoRecusado("A planilha está vazia.")
    cabecalho = list(primeiras[indice])
    while cabecalho and _vazio(cabecalho[-1]):
        cabecalho.pop()
    return indice + 1, cabecalho


def _estilo_de_cabecalho(aba, numero_do_cabecalho, de_indice, para_indice) -> None:
    """A coluna nova nasce com a cara das outras: o cabeçalho copia o estilo
    do último cabeçalho existente, e a largura acompanha."""
    from openpyxl.utils import get_column_letter

    if de_indice < 0:
        return
    modelo = aba.cell(row=numero_do_cabecalho, column=de_indice + 1)
    nova = aba.cell(row=numero_do_cabecalho, column=para_indice + 1)
    if modelo.has_style:
        nova._style = copy(modelo._style)
    largura = aba.column_dimensions[get_column_letter(de_indice + 1)].width
    aba.column_dimensions[get_column_letter(para_indice + 1)].width = max(largura or 0, len(str(nova.value or "")) + 4, 14)


def _preencher_xlsx(nome, dados, pedido, casador) -> Preenchimento:
    from openpyxl import load_workbook

    # Aqui NÃO é read_only: para escrever é preciso o modo normal. O limite
    # de 5 MiB e de linhas existe por causa deste momento. Sem data_only: as
    # fórmulas da pessoa continuam fórmulas no arquivo devolvido.
    try:
        livro = load_workbook(io.BytesIO(dados), keep_vba=Path(nome).suffix.lower() == ".xlsm")
    except Exception as exc:
        raise AnexoRecusado("Não consegui abrir esse arquivo como planilha.") from exc

    aba = _aba_pedida(livro, pedido.aba)
    numero_do_cabecalho, cabecalho = _cabecalho_da_aba(aba)
    i_chave = None if pedido.por_linha else _indice_da_coluna(cabecalho, pedido.coluna_chave)
    if i_chave is None and not pedido.por_linha:
        raise AnexoRecusado(f'A planilha não tem a coluna "{pedido.coluna_chave}".')
    i_rotulo = _indice_da_coluna(cabecalho, pedido.coluna_chave)

    largura_original = len(cabecalho)
    # Só a tabela principal: o bloco de premissas embaixo dela não é linha
    # da base, e contá-lo como "sem correspondência" seria ruído.
    valores = [tuple(c.value for c in linha) for linha in aba.iter_rows(min_row=1, max_row=aba.max_row or 1)]
    ultima = fim_da_tabela(valores, numero_do_cabecalho - 1)
    destinos, criadas, atualizadas = _destinos(cabecalho, pedido)
    formatos = []
    for indice, (destino, origem) in zip(destinos, pedido.colunas):
        if indice >= largura_original:
            aba.cell(row=numero_do_cabecalho, column=indice + 1, value=destino)
            _estilo_de_cabecalho(aba, numero_do_cabecalho, largura_original - 1, indice)
        formatos.append(e_percentual(destino) or e_percentual(origem))

    contagem = _Contagem()
    for numero in range(numero_do_cabecalho + 1, ultima + 1):
        if pedido.por_linha:
            if all(_vazio(aba.cell(row=numero, column=i + 1).value) for i in range(largura_original)):
                continue
            bruto = numero
            valor_do_rotulo = aba.cell(row=numero, column=i_rotulo + 1).value if i_rotulo is not None else None
            rotulo = valor_do_rotulo if not _vazio(valor_do_rotulo) else f"linha {numero}"
        else:
            bruto = aba.cell(row=numero, column=i_chave + 1).value
            rotulo = bruto
            if _vazio(bruto):
                continue
        situacao, valores, no_banco = casador.casar(bruto)
        if pedido.por_linha and situacao == "sem" and all(
            indice < largura_original and not _vazio(aba.cell(row=numero, column=indice + 1).value)
            for indice in destinos
        ):
            # UPDATE só das vazias: a consulta deixou de fora, de propósito, a
            # linha que já tinha valor. Ela não é "sem correspondência" — na
            # coluna Potencial, 157 linhas preenchidas viravam "0 de 230"
            # (2026-10-01).
            continue
        if not contagem.registrar(rotulo, situacao, no_banco, valores):
            continue
        for indice, percentual, valor in zip(destinos, formatos, valores):
            celula = aba.cell(row=numero, column=indice + 1)
            if not _escrever(celula.value, valor, _pode_sobrescrever(pedido, cabecalho, indice), contagem):
                continue
            celula.value = _para_celula(valor)
            # O número continua sendo 9,23 na célula: só o formato mostra
            # o símbolo. Assim a soma e o gráfico do Excel seguem valendo,
            # e quem abre o arquivo lê a unidade sem adivinhar.
            if percentual and isinstance(celula.value, (int, float)):
                celula.number_format = FORMATO_PERCENTUAL

    buffer = io.BytesIO()
    livro.save(buffer)
    livro.close()
    return contagem.resultado(buffer.getvalue(), nome, criadas, atualizadas, aba=aba.title)


# ------------------------------------------------ abas novas e notas (ADR-0031)

NOME_DAS_NOTAS = "Notas do Jarvis"
# Linhas que uma aba nova recebe. É o limite da planilha de download: a aba
# é o resultado de uma consulta, e ele já chega limitado a isto.
MAX_LINHAS_DA_ABA_NOVA = 50_000
# Linhas que um gráfico dentro da aba aceita. Acima disso ninguém lê barra
# nenhuma; a aba fica, o gráfico não.
MAX_LINHAS_DO_GRAFICO = 60
GRAFICOS_NA_ABA = {"barras", "colunas", "linha", "pizza"}
_PROIBIDOS_NO_TITULO = re.compile(r"[\[\]\*\?/\\:]")


def _livro_editavel(nome: str, dados: bytes):
    """(livro openpyxl, nome do arquivo final). CSV vira xlsx com a base
    numa aba "Dados": CSV não tem onde pôr uma aba nova."""
    from openpyxl import Workbook, load_workbook

    if not _e_csv(nome):
        try:
            return load_workbook(io.BytesIO(dados), keep_vba=Path(nome).suffix.lower() == ".xlsm"), nome
        except Exception as exc:
            raise AnexoRecusado("Não consegui abrir esse arquivo como planilha.") from exc
    livro = Workbook()
    aba = livro.active
    aba.title = "Dados"
    for linha in _linhas_do_csv(dados):
        aba.append([_para_celula(v) if not _vazio(v) else None for v in linha])
    return livro, str(Path(nome).with_suffix(".xlsx"))


def _salvar(livro) -> bytes:
    buffer = io.BytesIO()
    livro.save(buffer)
    livro.close()
    return buffer.getvalue()


def _titulo_livre(livro, desejado: str) -> str:
    """Nome de aba válido e que ainda não existe (31 caracteres, sem os
    símbolos que o Excel recusa)."""
    base = _PROIBIDOS_NO_TITULO.sub(" ", str(desejado or "Análise")).strip()[:31] or "Análise"
    existentes = {normalizar(t) for t in livro.sheetnames}
    titulo, n = base, 2
    while normalizar(titulo) in existentes:
        sufixo = f" ({n})"
        titulo, n = base[: 31 - len(sufixo)] + sufixo, n + 1
    return titulo


def _grafico(aba, tipo: str, colunas, linhas) -> bool:
    """Gráfico nativo do Excel sobre a própria aba: a primeira coluna é a
    categoria, as numéricas (até três) são as séries. Os números do gráfico
    são as células da aba — nada é desenhado à parte."""
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference

    if tipo not in GRAFICOS_NA_ABA or not linhas or len(linhas) > MAX_LINHAS_DO_GRAFICO or len(colunas) < 2:
        return False
    numericas = [
        i for i in range(1, len(colunas))
        if all(isinstance(l[i], (int, float, Decimal)) and not isinstance(l[i], bool) for l in linhas if l[i] is not None)
        and any(l[i] is not None for l in linhas)
    ][:1 if tipo == "pizza" else 3]
    if not numericas:
        return False
    grafico = {"barras": BarChart, "colunas": BarChart, "linha": LineChart, "pizza": PieChart}[tipo]()
    if tipo == "barras":
        grafico.type = "bar"
    elif tipo == "colunas":
        grafico.type = "col"
    ultima = len(linhas) + 1
    for i in numericas:
        grafico.add_data(Reference(aba, min_col=i + 1, min_row=1, max_row=ultima), titles_from_data=True)
    grafico.set_categories(Reference(aba, min_col=1, min_row=2, max_row=ultima))
    grafico.height, grafico.width = 9, 18
    from openpyxl.utils import get_column_letter

    aba.add_chart(grafico, f"{get_column_letter(len(colunas) + 2)}2")
    return True


def adicionar_aba(nome: str, dados: bytes, titulo: str, colunas, linhas, grafico: str = "") -> tuple:
    """Acrescenta uma aba com o resultado de uma consulta (REPORTING e
    TRANSFORMATION, ADR-0031). A base da pessoa não é tocada: o que é novo
    vai para aba nova. Devolve (dados, nome do arquivo, título da aba, se o
    gráfico entrou)."""
    from openpyxl.styles import Font

    livro, nome_final = _livro_editavel(nome, dados)
    titulo_final = _titulo_livre(livro, titulo)
    aba = livro.create_sheet(titulo_final)
    aba.append([str(c) for c in colunas])
    for celula in aba[1]:
        celula.font = Font(bold=True)
    linhas = [list(l) for l in list(linhas)[:MAX_LINHAS_DA_ABA_NOVA]]
    for linha in linhas:
        aba.append([_para_celula(v) for v in linha])
    for i, coluna in enumerate(colunas):
        from openpyxl.utils import get_column_letter

        aba.column_dimensions[get_column_letter(i + 1)].width = min(max(len(str(coluna)) + 4, 12), 45)
        if e_percentual(coluna):
            for (celula,) in aba.iter_rows(min_row=2, min_col=i + 1, max_col=i + 1):
                if isinstance(celula.value, (int, float)):
                    celula.number_format = FORMATO_PERCENTUAL
    aba.freeze_panes = "A2"
    com_grafico = _grafico(aba, (grafico or "").strip().lower(), list(colunas), linhas) if grafico else False
    return _salvar(livro), nome_final, titulo_final, com_grafico


def anotar(nome: str, dados: bytes, notas) -> tuple:
    """A aba "Notas do Jarvis": cada alteração com onde, o quê, por quê e de
    onde veio o dado (ADR-0031). Se o arquivo já tinha uma (a pessoa mandou
    de volta a planilha que o Jarvis devolveu), ela é substituída.

    `notas`: [{"onde", "o_que", "por_que", "origem", "resultado"}, ...].
    Devolve (dados, nome)."""
    from openpyxl.styles import Alignment, Font

    if not notas:
        return dados, nome
    livro, nome_final = _livro_editavel(nome, dados)
    for titulo in list(livro.sheetnames):
        if normalizar(titulo) == normalizar(NOME_DAS_NOTAS):
            del livro[titulo]
    aba = livro.create_sheet(NOME_DAS_NOTAS)
    cabecalho = ("Onde", "O que mudou", "Por quê", "De onde veio o dado", "Resultado")
    aba.append(cabecalho)
    for celula in aba[1]:
        celula.font = Font(bold=True)
    for nota in notas:
        aba.append([nota.get("onde", ""), nota.get("o_que", ""), nota.get("por_que", ""),
                    nota.get("origem", ""), nota.get("resultado", "")])
    for letra, largura in zip("ABCDE", (28, 40, 60, 60, 40)):
        aba.column_dimensions[letra].width = largura
    for linha in aba.iter_rows(min_row=2):
        for celula in linha:
            celula.alignment = Alignment(wrap_text=True, vertical="top")
    return _salvar(livro), nome_final


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
        abas = _linhas_do_xlsx(dados)
        # A aba é a mesma do preenchimento: pegar a primeira aqui e escrever
        # na terceira lá devolveria a tabela de outra planilha.
        procurada = normalizar(pedido.aba).replace(" ", "")
        brutas = next(
            (linhas for titulo, linhas in abas if normalizar(titulo).replace(" ", "") == procurada),
            abas[0][1],
        )
        uteis = [list(l) for l in brutas if any(v not in (None, "") for v in l)]
    if not uteis or pedido.por_linha:
        # Com `_linha`, a consulta já partiu das linhas da planilha.
        return []
    i_cabecalho = indice_do_cabecalho(uteis) or 0
    uteis = uteis[i_cabecalho:]

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
