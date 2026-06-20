FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

# uv build tool pinned by version + immutable digest (no floating tags).
COPY --from=ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (better layer caching).
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

# Application source.
COPY . .
RUN uv sync --no-dev --frozen

EXPOSE 8000

# Service entrypoints (overridden per service in compose / k8s):
#   API      : applies migrations then serves uvicorn (one process per pod in prod)
#   cpu worker: celery --pool=prefork -n cpu@%h -Q cpu
#   io worker : celery --pool=threads -n io@%h -Q io
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
