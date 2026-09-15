# Imagem única para os dois serviços da aplicação: web (Django/gunicorn) e
# worker (Celery). O worker só troca o start command no Railway (ADR-0012).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # manage.py e os apps vivem em app/ — sem isto "config.x" não resolve.
    PYTHONPATH=/app/app \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Mesma versão do uv que gerou o uv.lock: uma versão muito mais antiga pode
# não conseguir ler o lockfile.
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

# Dependências primeiro, para o cache de camada sobreviver a mudanças de
# código. --frozen exige uv.lock em dia.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Estáticos do Admin resolvidos no build, servidos pelo WhiteNoise.
# Nada aqui toca banco; SECRET_KEY tem fallback no settings.
RUN python app/manage.py collectstatic --noinput

# migrate no start: uma réplica web e evita o passo manual esquecido a cada
# deploy. gunicorn em [::] porque a rede privada do Railway é IPv6.
CMD ["sh", "-c", "python app/manage.py migrate --noinput && gunicorn config.wsgi:application --bind [::]:${PORT:-8000} --workers 2 --timeout 60 --access-logfile - --error-logfile -"]
