"""Saída de comandos de terminal em UTF-8.

O console do Windows usa cp1252 por padrão e estoura UnicodeEncodeError em
caracteres comuns nos nossos textos ("→", "—", emoji). O projeto de
referência levou o mesmo problema para um comando de produção, e o sintoma
(um traceback no meio da saída) não tem nada a ver com a causa.
"""

import sys


def usar_utf8_no_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
