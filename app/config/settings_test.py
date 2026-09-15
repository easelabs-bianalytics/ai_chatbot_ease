"""Settings da suíte de testes (apontado em `pyproject.toml`).

Diferenças deliberadas em relação a `config.settings`:

- **não carrega o `bi/.env`**, que tem credenciais reais: nenhum teste pode
  depender delas nem usá-las por acidente;
- **banco sempre local** (Postgres do docker-compose), ou
  `TEST_APP_DATABASE_URL` se ele estiver em outro lugar — nunca
  `APP_DATABASE_URL`, porque o pytest-django cria e apaga bancos `test_*` no
  servidor configurado;
- Celery em modo eager, sem Redis nem worker;
- estáticos sem manifest, para o Admin renderizar sem `collectstatic`.
"""

import os

os.environ["BI_SKIP_DOTENV"] = "1"

from config.env import database_from_env  # noqa: E402
from config.settings import *  # noqa: E402,F403

SECRET_KEY = "chave-usada-somente-nos-testes"
DEBUG = False

DATABASES = {
    "default": database_from_env(
        {"APP_DATABASE_URL": os.environ.get("TEST_APP_DATABASE_URL", "")}
    )
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
