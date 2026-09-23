"""O que o nome de uma coluna do resultado diz sobre a unidade dela.

O banco devolve `9.23`, e `9.23` tanto pode ser unidade, real ou por cento.
Quem dá a unidade é o nome da coluna, pela convenção das consultas de
referência: `share_pct`, `retencao_90d_pct`, `share_ease_varejo_ytd`.

Mora aqui, e não em quem desenha a tela, porque a mesma resposta aparece em
quatro lugares — a tabela, o rótulo do gráfico, o texto e a célula da
planilha devolvida — e eles não podem discordar sobre o que é percentual.
A tela tem a cópia desta regra em `web/static/web/app.js`; as duas andam
juntas.
"""

import re

_PERCENTUAL_NO_NOME = re.compile(
    r"(^|_)(pct|perc|percent|percentual|share|participacao|participação)(_|$)", re.I
)

# Formato do Excel para a célula preenchida: o valor continua sendo 9,23
# (soma e gráfico do arquivo seguem valendo) e só a exibição traz o símbolo.
FORMATO_PERCENTUAL = '0.00"%"'


def e_percentual(coluna) -> bool:
    return bool(_PERCENTUAL_NO_NOME.search(str(coluna or "")))
