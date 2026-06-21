# syntax=docker/dockerfile:1
#
# Multi-stage application image (FR-013, SC-006). The build stage carries the uv toolchain
# and resolves a self-contained virtualenv; the runtime stage is the minimal pinned slim
# base and copies ONLY the resolved env + app source — no uv, no compilers.
#
# The image is shared by every backend workload (command overridden per workload in k8s):
#   API       : uvicorn (one process per pod; migrations run in the migrate Job, NOT here)
#   cpu worker: celery --pool=prefork -n cpu@%h -Q cpu
#   io worker : celery --pool=threads -n io@%h -Q io
#   migrate   : alembic upgrade head

############################
# Build stage — resolve deps into /app/.venv with uv (build tools live here only).
############################
FROM python:3.13.14-slim@sha256:c33f0bc4364a6881bed1ec0cc2665e6c53c87a43e774aaeab88e6f17af105e4f AS build

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# uv build tool pinned by version + immutable digest (no floating tags). Build stage ONLY —
# the runtime stage deliberately carries no uv (the authoritative SC-006 check).
COPY --from=ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (better layer caching), then the project itself.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen
COPY . .
RUN uv sync --no-dev --frozen

############################
# Runtime stage — minimal pinned slim; no uv / no build toolchain (FR-013, SC-006).
############################
FROM python:3.13.14-slim@sha256:c33f0bc4364a6881bed1ec0cc2665e6c53c87a43e774aaeab88e6f17af105e4f AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copy only the resolved virtualenv + application source from the build stage. The venv is
# valid because build and runtime share the SAME pinned base (python at /usr/local/bin).
COPY --from=build /app /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
