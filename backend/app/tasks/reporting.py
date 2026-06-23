from __future__ import annotations

from datetime import UTC, datetime

from opentelemetry import trace

from app.tasks.celery_app import celery_app
from app.tasks.deps import get_worker_container

_tracer = trace.get_tracer("app.tasks.reporting")


@celery_app.task(name="app.tasks.reporting.stats_report_tick")
def stats_report_tick() -> None:
    """Beat-fired due-check (cpu/prefork). When the cadence is due, claim the slot and run the
    CPU-bound cycle, which enqueues the existing ``app.tasks.sending.deliver`` per recipient on io.
    No-op when reporting is disabled or not yet due (research §4/§6)."""
    with _tracer.start_as_current_span("stats_report_tick"):
        container = get_worker_container()
        if container.report_due.claim_if_due(datetime.now(UTC)):
            container.report_cycle.run_cycle()
