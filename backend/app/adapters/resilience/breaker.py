from __future__ import annotations

import threading
from typing import Any

import pybreaker
import structlog

from app.domain.errors import PermanentChannelError

_log = structlog.get_logger("app.resilience.breaker")


class _StateChangeListener(pybreaker.CircuitBreakerListener):
    """Emit a structured log line on every breaker state change (open/half-open/close)."""

    def __init__(self, key: str) -> None:
        self._key = key

    def state_change(self, cb: pybreaker.CircuitBreaker, old: Any, new: Any) -> None:
        _log.info(
            "circuit_breaker_state_change",
            breaker=self._key,
            old_state=getattr(old, "name", str(old)),
            new_state=getattr(new, "name", str(new)),
        )


class PyBreakerCircuitBreaker:
    """A thread-safe registry of pybreaker circuit breakers, one per channel/destination key
    (research §6). Implements the ``BreakerRegistry`` port used by ``application.resilience``.

    A ``PermanentChannelError`` is a single-message failure, not a provider-health signal, so it is
    excluded from the failure count; transient errors (429/timeout/5xx) trip the breaker."""

    def __init__(self, *, fail_max: int, reset_timeout: float) -> None:
        self._fail_max = fail_max
        self._reset_timeout = reset_timeout
        self._breakers: dict[str, pybreaker.CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> pybreaker.CircuitBreaker:
        with self._lock:
            breaker = self._breakers.get(key)
            if breaker is None:
                breaker = pybreaker.CircuitBreaker(
                    fail_max=self._fail_max,
                    reset_timeout=self._reset_timeout,
                    exclude=[PermanentChannelError],
                    listeners=[_StateChangeListener(key)],
                    name=key,
                )
                self._breakers[key] = breaker
            return breaker
