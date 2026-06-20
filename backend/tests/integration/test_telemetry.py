from __future__ import annotations

import json

import sentry_sdk
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def test_structured_startup_log_emitted(capsys, monkeypatch):
    import app.infra.telemetry as telemetry

    monkeypatch.setattr(telemetry, "_initialized", False)
    telemetry.init_telemetry()

    lines = [
        line for line in capsys.readouterr().out.splitlines() if "telemetry_initialized" in line
    ]
    assert lines, "no structured startup log line emitted"
    record = json.loads(lines[-1])  # structured == valid JSON
    assert record["event"] == "telemetry_initialized"
    assert record["level"] == "info"


def test_error_reporting_client_initialized(monkeypatch):
    import app.infra.telemetry as telemetry
    from app.settings import get_settings

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    get_settings.cache_clear()
    monkeypatch.setattr(telemetry, "_initialized", False)
    telemetry.init_telemetry()
    assert sentry_sdk.get_client().is_active()


def test_trace_span_recorded_for_readiness_request(monkeypatch):
    import app.infra.telemetry as telemetry

    # Ensure a real SDK TracerProvider is installed, then attach an in-memory exporter to it.
    # Works regardless of test ordering — the router's tracer forwards to the global provider.
    telemetry.init_telemetry()
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Unreachable DB/broker → /health returns promptly (503); the span must still be recorded.
    monkeypatch.setenv("DATABASE_URL_ASYNC", "postgresql+asyncpg://app:app@127.0.0.1:1/app")
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql+psycopg://app:app@127.0.0.1:1/app")
    monkeypatch.setenv("BROKER_URL", "amqp://guest:guest@127.0.0.1:1//")
    from app.infra.db import async_engine, sync_engine
    from app.settings import get_settings

    get_settings.cache_clear()
    async_engine._engine = None
    async_engine._sessionmaker = None
    sync_engine._engine = None
    sync_engine._sessionmaker = None

    from app.main import create_app

    with TestClient(create_app()) as client:
        client.get("/health")

    assert "health.aggregate" in {span.name for span in exporter.get_finished_spans()}
