from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration sourced from environment / .env (never hard-coded)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # Database — two engines, shared models (constitution Principle III).
    database_url_async: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    database_url_sync: str = "postgresql+psycopg://app:app@localhost:5432/app"

    # Celery broker (RabbitMQ).
    broker_url: str = "amqp://guest:guest@localhost:5672//"

    # Telemetry.
    otel_service_name: str = "notification-service"
    otel_exporter_otlp_endpoint: str | None = None
    sentry_dsn: str | None = None
    environment: str = "dev"

    # Bounded timeouts (seconds).
    readiness_check_timeout_s: float = 2.0  # per-subsystem bound; aggregate stays < 5s (SC-004)
    readiness_normal_budget_s: float = 1.0  # normal-case target (SC-005)
    smoke_timeout_s: float = 10.0  # smoke round-trip bound (SC-007)


@lru_cache
def get_settings() -> Settings:
    return Settings()
