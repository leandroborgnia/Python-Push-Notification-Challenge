from __future__ import annotations

import logging

import sentry_sdk
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from app.settings import Settings, get_settings

_initialized = False


def _init_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _init_tracing() -> None:
    # Set a real provider only if one is not already installed (lets tests install an
    # in-memory exporter first). Avoids OpenTelemetry's "already set" override warning.
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(TracerProvider())


def _init_sentry(settings: Settings) -> None:
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment)


def init_telemetry() -> None:
    """Idempotently wire structured logging, tracing, and error reporting (FR-016).

    Called on FastAPI startup and on each Celery worker process start.
    """
    global _initialized
    if _initialized:
        return
    settings = get_settings()
    _init_logging()
    _init_tracing()
    _init_sentry(settings)
    _initialized = True
    structlog.get_logger("app").info(
        "telemetry_initialized",
        service=settings.otel_service_name,
        environment=settings.environment,
    )
