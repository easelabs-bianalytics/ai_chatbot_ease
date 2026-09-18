"""Comando catalog_check: a conferência que o catálogo não dá sozinho."""

from io import StringIO

from django.core.management import call_command


def test_catalogo_do_projeto_passa_na_conferencia():
    """Roda o caminho completo do comando (catálogo + referências +
    validador). Se alguém acrescentar uma referência usando um schema que não
    está liberado, é aqui que aparece — e não numa pergunta de usuário."""
    saida = StringIO()

    call_command("catalog_check", stdout=saida)

    texto = saida.getvalue()
    assert "Catálogo consistente" in texto
    assert "cddd.fato_cdd" in texto
