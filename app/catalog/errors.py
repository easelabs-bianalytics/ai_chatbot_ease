class CatalogError(Exception):
    """Catálogo ou consultas de referência inválidos.

    Falha alto de propósito: com o catálogo errado, o validador de SQL pode
    liberar o que devia barrar. É melhor a aplicação não subir.
    """
