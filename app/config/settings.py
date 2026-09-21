"""Settings do chatbot de BI.

Tudo o que muda entre ambientes vem de variável de ambiente, documentada em
`.env.example`. Os valores padrão servem só ao desenvolvimento local com o
`docker-compose.yml`. A suíte de testes usa `config.settings_test`.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from config.env import database_from_env, env_bool, env_list

# bi/ — onde ficam .env, docs/ e as consultas de referência.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# O bi/.env tem credenciais reais. `config.settings_test` liga BI_SKIP_DOTENV
# antes de importar este módulo para que a suíte de testes nunca as enxergue.
if os.environ.get("BI_SKIP_DOTENV") != "1":
    load_dotenv(BASE_DIR / ".env")

# O fallback só existe para comandos sem .env (ex.: collectstatic no build da
# imagem). Nenhum ambiente real pode rodar com ele.
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure--dev-only-fallback--nao-usar-em-producao",
)

DEBUG = env_bool("DEBUG", default=False)

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

# Domínios (com esquema) autorizados a enviar POST — o do Railway precisa
# estar aqui, senão o login falha por CSRF. Ex.: https://bi.up.railway.app
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Atrás do proxy que termina o TLS (Railway), o Django recebe HTTP e acharia
# que o site é HTTP; o login do Admin falharia na checagem de Origin.
if env_bool("TRUST_PROXY_SSL_HEADER", default=True):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# Acesso por código enviado ao e-mail corporativo (web/acesso.py). Só entra
# quem lê uma caixa @easelabs.com.br — é o que restringe o app à empresa, e
# quem sai dela perde o acesso quando a TI desliga o e-mail.
DOMINIO_DE_ACESSO = "easelabs.com.br"
# Usuário e senha ficam desligados: com eles, a conta `demo` e qualquer
# senha antiga seriam uma porta de entrada sem e-mail da empresa. Só para
# desenvolvimento, e nunca em produção.
LOGIN_POR_SENHA = env_bool("LOGIN_POR_SENHA", default=False)

# A sessão expira depois de 30 dias SEM USO, não 30 dias depois do login: a
# cada requisição o prazo recomeça. Quem usa todo dia não é deslogado; um
# notebook esquecido não fica aberto para sempre.
SESSION_COOKIE_AGE = 30 * 24 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True

# E-mail — a mesma lógica do Cockpit (sales_force_crm/config/settings.py):
# console no desenvolvimento (o código aparece no terminal do runserver) e
# Gmail SMTP em produção. O remetente precisa ser a própria conta
# autenticada: o Gmail reescreve ou marca como spam um From de outro domínio.
# `EMAIL_ENVIO_REAL=1` liga o Gmail também em desenvolvimento, para testar o
# e-mail de verdade.
if DEBUG and not env_bool("EMAIL_ENVIO_REAL", default=False):
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "smtp.gmail.com"
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_TIMEOUT = 15
    # .get e não [...]: o collectstatic do build da imagem roda sem essas
    # variáveis. Se faltarem em produção, o envio falha e é registrado.
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", f"Jarvis · Ease Labs <{os.environ.get('EMAIL_HOST_USER', 'jarvis@localhost')}>"
)
# SECURE_SSL_REDIRECT fica desligado de propósito: o healthcheck da
# plataforma bate no container em HTTP e cairia em redirect infinito.


# Celery + Redis (ADR-0003)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6381/0")

# Cache = depósito temporário dos anexos (ADR-0024). É o mesmo Redis da fila,
# em OUTRO banco (/1): um `FLUSHDB` no cache não pode apagar tarefa
# enfileirada. Prazo padrão curto porque aqui não mora nada que precise
# durar — anexo vencido é anexo descartado, e isso é de propósito.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL.rsplit("/", 1)[0] + "/1",
        "TIMEOUT": 15 * 60,
    }
}

# Upload do anexo fica SÓ em memória. O padrão do Django grava em arquivo
# temporário no disco tudo acima de 2,5 MB — e a regra aqui é que o arquivo
# da pessoa não toca disco nenhum (ADR-0024). O teto acompanha o limite de
# 5 MiB de `attachments/limites.py`, com folga para o cabeçalho multipart.
FILE_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_TRACK_STARTED = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_ALWAYS_EAGER = False
# Se o worker morrer no meio do processamento, a tarefa é reentregue em vez
# de sumir: o padrão do Celery confirma antes de executar, e na referência
# isso deixava mensagens presas sem resposta para sempre. O orquestrador é
# idempotente para tornar a reentrega segura.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "conversations",
    "messaging",
    "ai_orchestrator",
    "datasource",
    "catalog",
    "reporting",
    "web",
]

MIDDLEWARE = [
    # PRIMEIRO de propósito: responde o health check do ALB antes da checagem
    # de ALLOWED_HOSTS, que recusaria o IP privado da task (ver o módulo).
    "config.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Serve os estáticos do Admin em produção (com DEBUG=0 o Django não serve).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Banco da APLICAÇÃO. O banco de negócio (RDS) nunca entra aqui — ADR-0002.
DATABASES = {"default": database_from_env(os.environ)}

# ADR-0011: sem esta configuração o DRF aplica AllowAny. Foi assim que os
# webhooks da referência ficaram abertos até o deploy revelar a falha. Aqui
# toda view nasce fechada; abrir exige declarar na própria view.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# collectstatic roda no build da imagem e o WhiteNoise serve daqui.
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
