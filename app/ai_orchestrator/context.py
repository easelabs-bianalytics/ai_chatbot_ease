"""Monta o contexto de cada chamada ao modelo (ADR-0015).

Mandar o documento inteiro (45 mil tokens) e o schema (13 mil) em toda
pergunta custava cerca de três vezes mais e enchia o contexto de regra que
não se aplicava. Aqui o contexto é montado por pergunta:

    núcleo comum + seção do tema (inteira) + seções vizinhas (resumidas)
    + as tabelas dessas seções no schema

A escolha do tema é determinística e por palavra-chave, de propósito: é
barata, é testável e não acrescenta uma chamada de modelo (mais uma coisa
para falhar) antes de toda pergunta. Quando a pergunta não casa com nada e
não há histórico, vai só o núcleo — em geral é conversa — e a IA pede a
seção se precisar de dado.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from ai_orchestrator.document import CHAVES, get_document
from ai_orchestrator.prompts import load_prompt

NUCLEO = "nucleo_v1"
MAX_SECOES = 3
# Quantos temas vão com as consultas de referência; o resto vai resumido.
MAX_COMPLETAS = 2
# O modelo avisa que a seção resumida não bastou (ver nucleo_v1.md).
PEDIDO_DE_SECAO = "PRECISO DA SEÇÃO"

# Peso 2 = termo que praticamente decide o tema; peso 1 = termo que também
# aparece em outros temas e só desempata. Os termos saem do vocabulário do
# próprio documento e das perguntas de exemplo dele.
_TERMOS = {
    "prescricao": {
        # "prescrever" muda de radical ao conjugar ("prescreveram"), e é
        # assim que o usuário escreve.
        2: ("prescri", "prescrev", "prescrit", "px ", "px1", "receit", "cdgmedico", "molecul",
            "canabidiol", "rx per capita"),
        1: ("medico", "crm", "especialidad", "neurolog", "psiquiatr", "brick", "categoria do medico", "share"),
    },
    "sell_out": {
        2: ("sell out", "sellout", "vendeu", "vendemos", "venda", "vendas", "dispens", "faturament",
            "market share", "unidades", "ticket", "mercado publico", "saude suplementar", "extras", "cdd",
            # "Share" sozinho é market share. Só com o peso 1 da prescrição,
            # "em quais estados temos mais share nos Extratos?" foi para o tema
            # errado e a IA respondeu share de PX (2026-09-23, caso B38). Quem
            # fala "share de PX" continua indo para a prescrição: "px " pesa 2.
            # As classes (Isolado, Extrato) NÃO entram aqui: aparecem em todo
            # tema, e "ruptura de Extrato" passaria a levar o Sell Out inteiro.
            "share"),
        1: ("mercado", "laboratori", "sku", "produto", "meta", "bateu", "realizado", "rede", "pdv",
            # "crescemos em relação ao MAT passado?" não tinha termo nenhum;
            # com a pontuação colada, sem pegar "matriz" ou "material"
            " mat ", " mat?", " mat.", " mat,"),
    },
    "estoque": {
        2: ("estoque", "ruptura", "carga", "recebiment", "dde", "centro de distribuic", " cd ", "cd ",
            "categoria de pdv", "categoria do pdv", "zerad", "abastec", "ean"),
        1: ("loja", "lojas", "rede", "pdv", "giro", "forecast", "projec"),
    },
    "pbm": {
        2: ("pbm", "adesao", "adesoes", "aderir", "voucher", "campanha", "desconto", "transac", "beneficio"),
        1: ("paciente", "consumidor", "cupom"),
    },
    "forca_vendas": {
        2: ("visit", "painel", "represent", "territorio", "setor", "cobertura", "gerente regional",
            "equipe", "hierarquia", "email do", "e-mail do"),
        1: ("gr ", " gr", "remota", "forca de vendas", "quem atende", "quem e o", "quem sao"),
    },
    # Índice de Conversão (seção 6). "IC" sozinho é curto demais para buscar
    # solto: vai com espaço e pontuação, como o " mat " do Sell Out.
    "ic": {
        # Peso 3: frases que só existem no IC e que também têm palavra de
        # prescrição e de venda ("convertendo a prescrição em venda"). Com
        # peso 2 empatavam com os dois temas e o IC ia só como resumo.
        3: ("indice de conversao", "troca de receit", "troca no balcao", "prescricao em venda",
            "receita em venda", "prescricao vira venda", "receita vira venda"),
        2: (" ic ", " ic?", " ic.", " ic,"),
        1: ("conversao", "converte"),
    },
}


def _sem_acento(texto: str) -> str:
    base = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in base if unicodedata.category(c) != "Mn")


def pontuar(pergunta: str) -> dict:
    """Nota de cada tema para a pergunta. Exposto para o teste e para o
    relatório: quando a IA erra a consulta, a primeira suspeita é o tema."""
    texto = " " + re.sub(r"\s+", " ", _sem_acento(pergunta)) + " "
    notas = {}
    for chave, pesos in _TERMOS.items():
        nota = sum(peso for peso, termos in pesos.items() for t in termos if t in texto)
        if nota:
            notas[chave] = nota
    return notas


_PORQUE = re.compile(
    r"\bpor\s*que\b|\bporque\b|\bpor qual motivo\b|\bo que explica\b|\bo que (?:causou|levou)\b|"
    r"\bqual (?:a|foi a) causa\b|\bmotivo d[aoe]\b|\bexplica(?:r)? (?:a|o|essa|esse)\b",
    re.I,
)

# Os temas que o roteiro de investigação atravessa (ADR-0025): a queda é
# medida no sell-out, localizada na força de vendas (GR, regional, setor
# vago) e explicada na prescrição do painel. Mandar os três completos custa
# centavos a mais; faltar um leva à chamada com o documento inteiro.
TEMAS_DA_INVESTIGACAO = ("sell_out", "forca_vendas", "prescricao")

# Tetos da investigação: são o que segura o custo. No pior caso, três
# chamadas ao planejador (a primeira e duas rodadas de aprofundamento) e
# quatro consultas por rodada. Uma pergunta de porquê sai por ~US$ 0,15 a
# 0,30, contra ~US$ 0,04 de uma pergunta de número.
MAX_RODADAS = 3
MAX_PASSOS_POR_RODADA = 4


def e_pergunta_de_porque(texto: str) -> bool:
    """"Por que caiu", "o que explica", "qual a causa" — pergunta que pede
    um racional, não um número."""
    return bool(_PORQUE.search(_sem_acento(texto or "")))


def escolher_secoes_da_investigacao(pergunta: str, historico=()) -> tuple:
    """O tema da pergunta primeiro, depois os do roteiro, até o limite."""
    ordem = list(escolher_secoes(pergunta, historico))
    for tema in TEMAS_DA_INVESTIGACAO:
        if tema not in ordem:
            ordem.append(tema)
    return tuple(ordem[:MAX_SECOES])


def escolher_secoes(pergunta: str, historico=()) -> tuple:
    """Temas da pergunta, do mais provável para o menos.

    Vazio significa "não identifiquei": quem chama manda só o núcleo, e a IA
    pede a seção se precisar de dado. O histórico entra porque seguimento (`E em agosto?`) não tem
    palavra nenhuma do tema — a pergunta anterior é que tinha.
    """
    notas = pontuar(pergunta)
    if not notas:
        for anterior in reversed(list(historico)):
            if anterior.direction == "in":
                notas = pontuar(anterior.text)
                if notas:
                    break
    if not notas:
        return ()

    ordenadas = sorted(notas.items(), key=lambda item: (-item[1], CHAVES.index(item[0])))
    return tuple(chave for chave, _ in ordenadas[:MAX_SECOES])


def filtrar_schema(schema_text: str, tabelas) -> str:
    """Só as linhas do snapshot das tabelas pedidas, mantendo os títulos de
    schema. Uma pergunta de estoque não precisa das 170 relações do banco."""
    if not schema_text:
        return ""
    alvo = {t.lower() for t in tabelas}
    linhas, schema_atual, escritas = [], None, 0
    for linha in schema_text.splitlines():
        if linha.startswith("## "):
            schema_atual = linha
            continue
        achado = re.match(r"^-\s+`([^`]+)`", linha)
        if achado and achado.group(1).lower() in alvo:
            if schema_atual:
                linhas.append("")
                linhas.append(schema_atual)
                schema_atual = None
            linhas.append(linha)
            escritas += 1
    if not escritas:
        return ""
    return "# Schema do banco de negócio (só as tabelas deste assunto)\n" + "\n".join(linhas).strip()


@dataclass(frozen=True)
class Contexto:
    texto: str
    secoes: tuple = ()
    completo: bool = False
    detalhes: dict = field(default_factory=dict)
    # Começo de `texto` que é igual em toda pergunta (`texto` sempre começa
    # com ele). Vazio no contexto completo: ali o documento vai inteiro, em
    # outra ordem, e não há o que reaproveitar entre perguntas.
    fixo: str = ""

    @property
    def tokens_estimados(self) -> int:
        # Estimativa grosseira (4 caracteres por token) só para registro e
        # relatório; o número que vale é o que a API devolve em usage.
        return len(self.texto) // 4


def _bloco(titulo: str, corpo: str) -> str:
    return f"\n\n# {titulo}\n\n{corpo.strip()}" if corpo.strip() else ""


def _prefixo_fixo(documento) -> str:
    """O trecho igual em toda pergunta: regras gerais, índice e núcleo.

    É onde a chamada ao modelo marca o fim do cache (ver
    `OpenAIProvider.plan`). Tudo que vem depois — tema, schema, histórico,
    pergunta — muda de uma pergunta para outra e quase nunca é reaproveitado.
    """
    return (
        _bloco("Regras gerais do documento de referência", documento.preambulo)
        + _bloco("Temas do documento", documento.indice + "\n\n" + load_prompt(NUCLEO))
    )


def montar_contexto_do_plano(
    catalog, pergunta: str, historico=(), completo: bool = False, temas_completos: int = MAX_COMPLETAS,
    investigacao: bool = False,
) -> Contexto:
    """Contexto da chamada que escreve o SQL.

    `temas_completos` sobe quando há planilha anexada (ADR-0024): ela costuma
    cruzar três temas de uma vez (PX, sell-out e força de vendas, no caso
    real de 2026-09-21), e o terceiro em resumo fez o modelo pedir o
    documento inteiro — 47 mil tokens e US$ 0,125, contra uns centavos de
    fração a mais por mandar o terceiro tema completo."""
    documento = get_document(catalog)
    fixo = _prefixo_fixo(documento)
    if completo:
        escolhidas = ()
    elif investigacao:
        escolhidas = escolher_secoes_da_investigacao(pergunta, historico)
        temas_completos = MAX_SECOES
    else:
        escolhidas = escolher_secoes(pergunta, historico)

    if completo:
        texto = (
            _bloco("Consultas de referência", catalog.references_text)
            + _bloco("Schema do banco de negócio", catalog.schema_text)
        )
        return Contexto(texto=texto.strip(), secoes=CHAVES, completo=True,
                        detalhes={"motivo": "segunda tentativa"})

    if not escolhidas:
        # Sem tema reconhecido: quase sempre é conversa ("quem é você?",
        # "obrigado"). Mandar o documento inteiro custava ~34 mil tokens por
        # um cumprimento. Vai o mínimo; se a pergunta precisar de dado, a IA
        # pede a seção (PRECISO DA SEÇÃO) e o sistema reenvia completo.
        return Contexto(texto=fixo.strip(), secoes=(), completo=False, fixo=fixo.strip(),
                        detalhes={"motivo": "tema não identificado"})

    secoes = [documento.por_chave(c) for c in escolhidas]
    tabelas = set()
    for secao in secoes:
        tabelas |= secao.tabelas

    partes = [
        fixo,
        _bloco(f"Tema da pergunta: {secoes[0].titulo}", secoes[0].texto),
    ]
    # Dois temas vão inteiros porque pergunta que cruza áreas é frequente e
    # o resumo não basta: medido em 2026-09-17, a IA pediu o documento
    # inteiro numa pergunta cruzada e a segunda chamada custou 44 mil tokens
    # e 80 segundos — mais caro que mandar a segunda seção completa desde o
    # início. Do terceiro tema em diante vai o resumo.
    for secao in secoes[1:temas_completos]:
        partes.append(_bloco(f"Tema relacionado: {secao.titulo}", secao.texto))
    for secao in secoes[temas_completos:]:
        partes.append(_bloco(f"Tema relacionado (resumo): {secao.titulo}", secao.resumo))
    partes.append("\n\n" + filtrar_schema(catalog.schema_text, tabelas))

    return Contexto(
        texto="".join(partes).strip(),
        secoes=escolhidas,
        completo=False,
        fixo=fixo.strip(),
        detalhes={"tabelas": len(tabelas), "notas": pontuar(pergunta)},
    )


def montar_contexto_da_resposta(catalog, secoes=()) -> Contexto:
    """Contexto da chamada que redige a resposta.

    Ela não recebe o documento: quem escreve o texto precisa do resultado da
    consulta e das regras de redação, não das regras de SQL. Das regras de
    negócio, vai só o preâmbulo — é o que diz como falar de dado que não
    existe."""
    documento = get_document(catalog)
    return Contexto(
        texto=_bloco("Regras gerais do documento de referência", documento.preambulo).strip(),
        secoes=tuple(secoes),
    )
