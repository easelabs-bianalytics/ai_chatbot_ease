# Imagem do Jarvis, multiestágio no padrão do sales_force_crm/Dockerfile
# (pedido da DBA): o estágio `builder` tem compilador e headers; a imagem
# final leva só o que roda, com usuário sem privilégio.
#
# Uma imagem para os dois containers da task (ver infra/modules/compute/
# jarvis.tf no sales_force_crm): `jarvis-web` usa o CMD daqui; o
# `jarvis-worker` troca o comando por `celery -A config worker -P solo`.
#
# uv no lugar do Poetry do Cockpit: o lock deste projeto é o uv.lock. A
# estrutura é a mesma — só muda o instalador.

# =============================================
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Mesma versão do uv que gerou o uv.lock: uma versão muito mais antiga pode
# não conseguir ler o lockfile.
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

WORKDIR /app

# Dependências primeiro, para o cache de camada sobreviver a mudanças de
# código. --frozen exige uv.lock em dia.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Estáticos resolvidos no build e servidos pelo WhiteNoise. Nada aqui toca o
# banco; SECRET_KEY tem fallback no settings só para este comando.
ENV PYTHONPATH=/app/app \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings
RUN python app/manage.py collectstatic --noinput

# =============================================
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # manage.py e os apps vivem em app/ — sem isto "config.x" não resolve.
    PYTHONPATH=/app/app \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings

# Só a biblioteca de execução do Postgres; compilador e headers ficaram no
# builder.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash app

WORKDIR /app
# O .venv do builder funciona aqui porque as duas imagens partem do mesmo
# python:3.12-slim — o interpretador está no mesmo caminho.
COPY --from=builder --chown=app:app /app /app

USER app
EXPOSE 8000

# Sem `migrate` no start: em produção ele é uma task avulsa, rodada antes do
# deploy (passo 10 da Fase 9), e não algo que cada container repete ao subir.
# 0.0.0.0 porque a VPC é IPv4 (o `[::]` antigo era da rede do Railway).
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
