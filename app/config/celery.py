"""App Celery do projeto (ADR-0003).

A API do chat só persiste a pergunta e enfileira; planejamento, consulta e
redação rodam em tarefa assíncrona, fora da requisição HTTP.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
