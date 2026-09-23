"""Textos determinísticos do orquestrador.

Ficam aqui, e não no prompt, porque são respostas que o sistema dá sem
chamar a IA — e porque um texto fixo é mais fácil de revisar com o time de
BI do que uma instrução esperando que o modelo obedeça.
"""

NAO_SEI = (
    "Não encontrei esse dado nas tabelas que eu conheço. Registrei sua "
    "pergunta para o time de BI avaliar se dá para incluir no catálogo."
)

FORA_DE_ESCOPO_ESCRITA = (
    "Eu só consulto dados, não altero nada: meu acesso ao banco é somente "
    "leitura. Posso responder perguntas sobre os números."
)

# Assunto que não é o meu: desconversa e devolve a conversa para o que o
# assistente existe para fazer. Sem explicar por que não responde, sem
# julgar a pergunta e sem deixar a porta entreaberta ("posso falar disso
# em linhas gerais"), que é por onde a insistência entra.
FORA_DE_ESCOPO = (
    "Esse assunto está fora do que eu faço. Estou aqui para ajudar com "
    "análises e consultas no ecossistema de dados da Ease Labs — sell-out, "
    "estoque, prescrições, PDVs, time de campo. Quer que eu veja algum "
    "desses números?"
)

TENTATIVA_DE_INJECAO = (
    "Minhas instruções são fixas e eu não mudo de papel: consulto a base de "
    "BI da Ease Labs em modo somente leitura e respondo sobre esses dados. "
    "Me diga qual número você precisa que eu busco."
)

MENSAGEM_SEM_PERGUNTA = (
    "Não consegui entender a pergunta. Pode escrever o que você precisa "
    "saber, com o período e o recorte (SKU, PDV, médico, território)?"
)

FALHA_DA_IA = (
    "Tive um problema técnico para montar a resposta agora. Pode tentar de "
    "novo em alguns instantes?"
)

FALHA_DO_BANCO = (
    "Não consegui executar a consulta no banco: {erro}. Se continuar, avise "
    "o time de BI."
)

CONSULTA_NAO_APROVADA = (
    "Não consegui montar uma consulta segura para essa pergunta ({motivo}). "
    "Registrei o caso para o time de BI."
)

DADO_INDISPONIVEL = (
    "Essa informação ainda não está disponível na nossa base de dados. "
    "Registrei o pedido para o time de BI. Posso ajudar com outra análise?"
)

# Os dois avisos de limite são discretos de propósito: não é erro de quem
# perguntou, e não há nada que ele possa fazer além de avisar o time.
LIMITE_DE_CUSTO = (
    "O limite de uso da IA deste mês foi atingido. Por favor, fale com o "
    "time de BI & Analytics para verificar a situação."
)

# O da pessoa é diferente dos outros dois: aqui há o que fazer — voltar
# amanhã, ou pedir ao time. Por isso ele diz o número e diz quando volta.
LIMITE_DIARIO = "Você atingiu 100% do limite de perguntas diário. A cota volta amanhã."

LIMITE_SEMANAL = "Você atingiu 100% do limite de perguntas semanal. A cota volta na segunda."

SEM_CREDITOS = (
    "No momento estou sem créditos para consultar os dados. Por favor, fale "
    "com o time de BI & Analytics para verificar a situação."
)

CONVERSA_COM_NUMERO = (
    "Para falar de números eu preciso consultar os dados. Me diga o período "
    "e o recorte que você quer, que eu verifico no banco."
)

RESULTADO_VAZIO = (
    "A consulta rodou e não retornou nenhuma linha, e a verificação que fiz em "
    "seguida não esclareceu o motivo. Isso quase nunca quer dizer que não houve "
    "movimento: costuma ser um filtro que não casou com o cadastro — um nome "
    "escrito de outro jeito, uma categoria que no banco tem outro rótulo, ou um "
    "período ainda sem carga. Me diga de outro jeito o que você procura, ou peça "
    "a lista do que existe naquele campo, que eu confiro."
)


def ajuda(catalog) -> str:
    """Os temas que o documento de referência cobre hoje: é a resposta
    honesta para "o que você sabe responder?".

    Saem das seções do documento, e não de um texto fixo, para não envelhecer
    quando o time de BI acrescentar um tema. Os 96 títulos de consulta, que
    eram listados antes, viravam uma parede de texto."""
    from ai_orchestrator.document import get_document

    temas = [f"- {secao.titulo}" for secao in get_document(catalog).secoes]
    return (
        "Sou o Jarvis, copiloto de dados da Ease Labs. Respondo perguntas de negócio "
        "consultando a base de BI, mostro de onde veio cada número e aviso "
        "quando o dado não existe. Posso ajudar com:\n"
        + "\n".join(temas)
        + "\n\nPergunte em português, dizendo o período e o recorte — por "
        "exemplo: *Quantas unidades a Pague Menos dispensou por mês em 2026?*"
    )

ANEXO_VENCIDO = (
    "O arquivo que você anexou já não está mais disponível — eles ficam guardados "
    "por pouco tempo de propósito, e este venceu. Envie de novo com a pergunta, "
    "que eu processo na hora."
)

PLANILHA_SEM_CASAMENTO = (
    "Não consegui identificar qual coluna da sua planilha casa com o dado pedido. "
    "Diga na pergunta qual coluna identifica cada linha (produto, rede, setor) e "
    "qual coluna devo preencher."
)

BANCO_INDISPONIVEL = (
    "O banco de dados não respondeu agora. Não é problema na sua pergunta — "
    "tente de novo em alguns minutos. Se continuar, avise o time de BI."
)

INVESTIGACAO_SEM_DADO = (
    "Tentei investigar, mas nenhuma das consultas trouxe dado para sustentar "
    "uma explicação. Tente com o período e o recorte mais específicos — por "
    "exemplo, o mês, o canal ou a regional."
)

RESSALVA_DE_FORECAST = (
    "Esta é uma projeção, feita a partir do histórico. Para uma visão mais "
    "assertiva e factual de reposição, confira o **dashboard de Forecast de "
    "Reposição**."
)
