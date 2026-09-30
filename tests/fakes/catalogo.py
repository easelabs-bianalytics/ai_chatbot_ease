"""O catálogo real com o bloqueio de colunas que valeu até 2026-09-30.

Desde então o catálogo real não bloqueia coluna nenhuma (decisão do Rubens,
O-02): dado de pessoa física pode ser consultado e compartilhado. O
MECANISMO continua no código e precisa continuar provado — se um dia alguém
voltar a listar colunas em `colunas_bloqueadas`, o validador e o snapshot
têm de barrá-las. Estes testes usam a lista antiga como exemplo.
"""

from dataclasses import replace

from catalog.loader import load_catalog

CONSUMIDOR = frozenset({
    "cpf_cons", "nome_cons", "data_nasc", "e_mail", "celular", "telefone", "cep_cons", "bairro_cons",
    "endereco_cons", "nr_endereco_cons", "compl_endereco_cons", "cartao_cons", "opt_e_mail", "opt_sms",
    "opt_fone", "opt_correio",
})

BLOQUEIO_DE_TESTE = {
    "pbm.fato_pbm_transacoes": CONSUMIDOR,
    "pbm.fato_pbm_adesoes": CONSUMIDOR,
    "cddd.adesao": CONSUMIDOR,
    "audit.rx_cadastro_mais_recente": frozenset({"cpf", "email", "celular", "endereco"}),
    "audit.rx_cadastro_pdv": frozenset({"email", "telefone1", "telefone2", "telefone3"}),
    "audit.trade_cadastro_estabelecimento": frozenset({"email", "telefone1", "telefone2", "telefone3"}),
    "audit.vw_fato_pbm_remota": frozenset({"telefone"}),
    "audit.vw_fato_prescricao_remota": frozenset({"telefone"}),
    "estoque_redes.fato_sell_in": frozenset({"cpfcnpj"}),
    "estoque_redes.rx_cadastro_pdv": frozenset({"email"}),
}


def catalogo_com_bloqueio():
    return replace(load_catalog(), blocked_columns=dict(BLOQUEIO_DE_TESTE))
