from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Time source — injected so token expiry and poll windows are testable."""

    def now(self) -> datetime: ...


class SystemClock:
    """Production clock: timezone-aware UTC wall time."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Test clock: returns a fixed instant, advanceable via :meth:`advance`."""

    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant

    def advance(self, *, seconds: float = 0.0) -> None:
        from datetime import timedelta

        self._instant = self._instant + timedelta(seconds=seconds)

    def set(self, instant: datetime) -> None:
        self._instant = instant
