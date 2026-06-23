"""Pure domain for the server-wide stats-report (no SQLAlchemy/FastAPI/Celery/matplotlib).

Holds the report cadence value object, the 24-bucket per-UTC-hour histogram, and the report scope
descriptor. Validation rules live here so the API (async) and the worker (sync) share one truth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.domain.errors import ValidationError

# Cadence is stored as an integer number of seconds.
DISABLED = 0
MIN_INTERVAL_SECONDS = 86_400  # 24 h — the smallest enabled cadence (FR-008)
DEFAULT_INTERVAL_SECONDS = 2_592_000  # 30 d — the provisioned default (FR-009)

HOURS_PER_DAY = 24


@dataclass(frozen=True, slots=True)
class StatsReportConfig:
    """The single, server-wide report cadence + its scheduling anchor.

    ``interval_seconds == 0`` disables reporting; ``>= 86_400`` enables it. Values in ``1..86_399``
    are never stored — :meth:`validate_interval` rejects them with a domain ``ValidationError``.
    """

    interval_seconds: int
    anchor_at: datetime

    @property
    def is_enabled(self) -> bool:
        return self.interval_seconds != DISABLED

    def next_run_at(self) -> datetime | None:
        """When the next report is due, or ``None`` while reporting is disabled."""
        if not self.is_enabled:
            return None
        return self.anchor_at + timedelta(seconds=self.interval_seconds)

    def is_due(self, now: datetime) -> bool:
        """True when reporting is enabled and ``now`` has reached the next run time."""
        next_run = self.next_run_at()
        return next_run is not None and now >= next_run

    @staticmethod
    def validate_interval(seconds: int) -> None:
        """Raise :class:`ValidationError` for a below-minimum interval (``1..86_399``).

        ``0`` (disable) and ``>= 86_400`` are valid; the actionable message is surfaced as 422.
        """
        if seconds != DISABLED and seconds < MIN_INTERVAL_SECONDS:
            raise ValidationError(
                f"interval_seconds must be 0 (disable) or at least 86400 (24 hours); got {seconds}"
            )

    def with_interval(self, seconds: int, now: datetime) -> StatsReportConfig:
        """Return a copy with a validated new interval and the anchor reset to ``now`` (FR-010)."""
        self.validate_interval(seconds)
        return StatsReportConfig(interval_seconds=seconds, anchor_at=now)


@dataclass(frozen=True, slots=True)
class HourHistogram:
    """Per-UTC-hour send counts — always exactly 24 buckets (index = hour 00..23)."""

    counts: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.counts) != HOURS_PER_DAY:
            raise ValidationError(
                f"HourHistogram requires exactly {HOURS_PER_DAY} buckets; got {len(self.counts)}"
            )

    @staticmethod
    def from_hour_counts(pairs: Mapping[int, int]) -> HourHistogram:
        """Build a 24-bucket histogram from a sparse ``{hour: count}`` mapping (missing → 0)."""
        return HourHistogram(tuple(pairs.get(hour, 0) for hour in range(HOURS_PER_DAY)))

    @property
    def total(self) -> int:
        return sum(self.counts)


class ReportScope(StrEnum):
    """Whether a report covers one user's own sends or the whole server (admin-only)."""

    PERSONAL = "personal"
    GLOBAL = "global"

    def title_for(self, *, email: str) -> str:
        """The email subject / chart title for this scope (``title`` is reserved by ``str``)."""
        if self is ReportScope.GLOBAL:
            return "Server-wide notification activity (per UTC hour)"
        return f"Your notification activity (per UTC hour) — {email}"

    @property
    def label(self) -> str:
        return "Global" if self is ReportScope.GLOBAL else "Personal"
