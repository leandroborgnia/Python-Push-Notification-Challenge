from __future__ import annotations

from typing import Any

from celery import Celery
from celery.signals import worker_process_init

from app.settings import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "notification_service",
        broker=settings.broker_url,
        backend=None,
        include=["app.tasks.liveness", "app.tasks.sending", "app.tasks.reporting"],
    )
    app.conf.update(
        task_ignore_result=True,
        result_backend=None,
        task_default_queue="cpu",
        task_create_missing_queues=True,
        worker_hijack_root_logger=False,
    )
    # Beat fires a static due-check tick on the cpu pool; the actual cadence lives in the DB
    # (stats_report_config), so this single static entry covers any interval (research §4).
    app.conf.beat_schedule = {
        "stats-report-due-check": {
            "task": "app.tasks.reporting.stats_report_tick",
            "schedule": settings.stats_report_due_check_interval_s,
            "options": {"queue": "cpu"},
        }
    }
    return app


celery_app = create_celery_app()


@worker_process_init.connect
def _init_worker_telemetry(**_: Any) -> None:
    # Telemetry wired on every worker process (FR-016).
    from app.infra.telemetry import init_telemetry

    init_telemetry()
