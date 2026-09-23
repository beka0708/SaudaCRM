# Образ приложения. Один и тот же используют web, bot и cron —
# отличаются только командой запуска.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

# curl — для healthcheck, postgresql-client — для pg_dump/psql изнутри
# контейнера приложения (ручной бэкап через make, автоматический делает
# отдельный сервис backup).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# uv — тот же менеджер пакетов, что и в разработке (в проекте нет pip).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Зависимости отдельным слоем: пересобираются только при изменении
# pyproject/lock, а не на каждую правку кода.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Не от root: если кто-то пролезет через приложение, прав на систему у него не будет.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app
USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]
