from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import structlog
from opentelemetry import trace

from app.domain.stats import HourHistogram, ReportScope
from app.ports.graph import GraphRenderer
from app.ports.repositories import (
    AccountRef,
    SyncReportAggregationRepository,
    SyncReportSendRepository,
    SyncStatsConfigRepository,
)

_log = structlog.get_logger("app.reporting")
_tracer = trace.get_tracer("app.application.reporting")


@dataclass(frozen=True, slots=True)
class ReportCycleResult:
    """Telemetry summary of one cycle."""

    accounts: int
    deliveries: int


class ReportCycleService:
    """The CPU-bound cycle body (runs on the ``cpu`` pool). Aggregates once, renders a 24-bar PNG
    per scope, persists a server-owned report ``dispatch``/``delivery`` per recipient, enqueues the
    existing ``deliver`` task. Every account gets a personal graph (all-zero if it never sent); the
    admin additionally gets the global graph (research §6). Framework-free."""

    def __init__(
        self,
        *,
        aggregation: SyncReportAggregationRepository,
        report_sends: SyncReportSendRepository,
        renderer: GraphRenderer,
        enqueue_deliver: Callable[[UUID], None],
    ) -> None:
        self._aggregation = aggregation
        self._report_sends = report_sends
        self._renderer = renderer
        self._enqueue_deliver = enqueue_deliver

    def run_cycle(self) -> ReportCycleResult:
        with _tracer.start_as_current_span("report.cycle") as span:
            per_user = self._aggregation.per_user_hour_counts()
            global_counts = self._aggregation.global_hour_counts()
            accounts = self._aggregation.list_accounts()

            enqueued = 0
            for account in accounts:
                personal = HourHistogram.from_hour_counts(per_user.get(account.id, {}))
                self._enqueue_deliver(self._create(account, ReportScope.PERSONAL, personal))
                enqueued += 1
                if account.is_admin:
                    global_hist = HourHistogram.from_hour_counts(global_counts)
                    self._enqueue_deliver(self._create(account, ReportScope.GLOBAL, global_hist))
                    enqueued += 1

            span.set_attribute("report.accounts", len(accounts))
            span.set_attribute("report.deliveries", enqueued)
            _log.info("report_cycle_complete", accounts=len(accounts), deliveries=enqueued)
            return ReportCycleResult(accounts=len(accounts), deliveries=enqueued)

    def _create(self, account: AccountRef, scope: ReportScope, histogram: HourHistogram) -> UUID:
        title = scope.title_for(email=account.email)
        png = self._renderer.render_hour_histogram(histogram.counts, title=title)
        body = (
            f"{scope.label} notification activity over the last period: "
            f"{histogram.total} send(s) reaching 'sent'. See the attached per-UTC-hour graph."
        )
        return self._report_sends.create_report_delivery(
            to_email=account.email, subject=title, body=body, png=png
        )


class ReportDueService:
    """Decides whether a cycle is due and claims the slot by advancing the anchor (research §4)."""

    def __init__(self, *, config: SyncStatsConfigRepository) -> None:
        self._config = config

    def claim_if_due(self, now: datetime) -> bool:
        """``True`` (and set ``anchor_at = now``, the claim time) iff due; else ``False``."""
        with _tracer.start_as_current_span("report.due_check") as span:
            config = self._config.get()
            due = config.is_due(now)
            span.set_attribute("report.due", due)
            if due:
                self._config.advance_anchor(now)
                _log.info("report_due_claimed", anchor=now.isoformat())
            return due
