from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# A deliberately non-prod placeholder so dev/test can sign tokens without committing a real
# secret (constitution Principle VI). The validator below refuses it outside dev.
_PLACEHOLDER_JWT_SECRET = "dev-insecure-placeholder-not-for-prod"

# The seeded admin's dev-only password. Committed because it is a placeholder, not a secret; the
# validator below refuses it outside dev (FR-002), mirroring the JWT-secret pattern.
_PLACEHOLDER_ADMIN_PASSWORD = "admin"


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
    readiness_check_timeout_s: float = 2.0  # aggregate per-check hard bound; < 5s (SC-004)
    worker_ping_timeout_s: float = 0.8  # control.ping window; < check bound and < 1s (SC-005)
    readiness_normal_budget_s: float = 1.0  # normal-case target (SC-005)
    smoke_timeout_s: float = 10.0  # smoke round-trip bound (SC-007)

    # Auth (constitution Principle VI). The secret has a non-prod placeholder default so dev/test
    # can sign tokens; the validator below fails fast in any non-dev environment that left it unset.
    jwt_secret: str = _PLACEHOLDER_JWT_SECRET
    jwt_alg: str = "HS256"
    access_token_ttl_min: int = 30
    verify_token_ttl_h: int = 24
    reset_token_ttl_h: int = 1

    # Auth email — a real, direct SMTP path (aiosmtplib), separate from the simulated channels.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "no-reply@notification.local"
    # Public base URL of the SPA, used to build clickable verify/reset links in auth emails. Dev
    # default is the kind ingress host; prod overrides via APP_BASE_URL (cf. cors_allow_origins).
    app_base_url: str = "http://app.localhost"

    # Admin account & stats-report (004). Credentials come from env; the committed defaults are a
    # dev-only placeholder refused outside dev by the validator below (FR-002, Principle VI).
    admin_email: str = "admin@localhost"
    admin_password: str = _PLACEHOLDER_ADMIN_PASSWORD
    # From-address for report emails; falls back to mail_from when unset.
    report_mail_from: str | None = None
    # Celery Beat tick cadence — how often the due-check fires (the cadence itself lives in the DB).
    stats_report_due_check_interval_s: float = 60.0

    # CORS — origins permitted to call the API from a browser (the SPA at app.localhost). The
    # list is env-overridable (pydantic parses a JSON array) and MUST stay an explicit allow-list,
    # never "*" (Principle I/VI). The SPA authenticates with a Bearer header, not cookies.
    cors_allow_origins: list[str] = ["http://app.localhost"]

    # Simulated channel provider (HTTP base URL; respx-mocked in tests).
    provider_base_url: str = "http://localhost:9000"
    # Where the provider POSTs email/push delivery confirmations (our webhook). The worker passes
    # this to the provider as the callback URL.
    webhook_callback_url: str = "http://localhost:8000/api/v1/webhooks/delivery"

    # Resilience knobs (application/ uses these — adapters stay dumb).
    retry_max_attempts: int = 3
    retry_backoff_base_s: float = 0.5
    breaker_fail_max: int = 5
    breaker_reset_timeout_s: float = 30.0
    sms_poll_interval_s: float = 3.0
    sms_poll_window_s: float = 30.0

    @model_validator(mode="after")
    def _require_real_jwt_secret_outside_dev(self) -> Settings:
        if self.environment != "dev" and (
            not self.jwt_secret or self.jwt_secret == _PLACEHOLDER_JWT_SECRET
        ):
            raise ValueError(
                "JWT_SECRET must be set to a real secret when ENVIRONMENT is not 'dev' "
                "(refusing the non-prod placeholder)."
            )
        return self

    @model_validator(mode="after")
    def _require_real_admin_password_outside_dev(self) -> Settings:
        if self.environment != "dev" and (
            not self.admin_password or self.admin_password == _PLACEHOLDER_ADMIN_PASSWORD
        ):
            raise ValueError(
                "ADMIN_PASSWORD must be set to a real secret when ENVIRONMENT is not 'dev' "
                "(refusing the non-prod placeholder)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
