from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pybreaker
import pytest

from app.adapters.resilience.breaker import PyBreakerCircuitBreaker
from app.application.resilience import IdempotencyGuard, ResiliencePolicy
from app.domain.errors import PermanentChannelError, TransientChannelError


class _PassThroughBreaker:
    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)


class _PassThroughRegistry:
    def get(self, key: str) -> _PassThroughBreaker:
        return _PassThroughBreaker()


def _policy() -> ResiliencePolicy:
    return ResiliencePolicy(breakers=_PassThroughRegistry(), max_attempts=3, backoff_base_s=0.0)


def test_retry_succeeds_after_transient_failures() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientChannelError("429")
        return "ok"

    assert _policy().run("k", flaky) == "ok"
    assert calls["n"] == 3  # two retries then success


def test_retry_exhausts_and_reraises() -> None:
    calls = {"n": 0}

    def always_fail() -> str:
        calls["n"] += 1
        raise TransientChannelError("timeout")

    with pytest.raises(TransientChannelError):
        _policy().run("k", always_fail)
    assert calls["n"] == 3  # stop_after_attempt(3)


def test_permanent_error_is_not_retried() -> None:
    calls = {"n": 0}

    def permanent() -> str:
        calls["n"] += 1
        raise PermanentChannelError("bad request")

    with pytest.raises(PermanentChannelError):
        _policy().run("k", permanent)
    assert calls["n"] == 1  # not a transient error → no retry


def test_breaker_opens_after_consecutive_failures() -> None:
    registry = PyBreakerCircuitBreaker(fail_max=3, reset_timeout=30)
    breaker = registry.get("email:to@example.com")
    calls = {"n": 0}

    def fail() -> None:
        calls["n"] += 1
        raise TransientChannelError("boom")

    # Drive failures until the breaker trips (the tripping call raises CircuitBreakerError).
    for _ in range(3):
        with pytest.raises((TransientChannelError, pybreaker.CircuitBreakerError)):
            breaker.call(fail)
    assert breaker.current_state == "open"

    # When open, the breaker fails fast and does NOT invoke fail().
    calls_before = calls["n"]
    with pytest.raises(pybreaker.CircuitBreakerError):
        breaker.call(fail)
    assert calls["n"] == calls_before


def test_permanent_error_excluded_from_breaker_count() -> None:
    registry = PyBreakerCircuitBreaker(fail_max=2, reset_timeout=30)
    breaker = registry.get("email:to@example.com")

    def permanent() -> None:
        raise PermanentChannelError("nope")

    for _ in range(3):
        with pytest.raises(PermanentChannelError):
            breaker.call(permanent)
    # Still closed — permanent errors don't trip the breaker.
    assert breaker.current_state == "closed"


class _FakeIdempotencyRepo:
    def __init__(self) -> None:
        self._claimed: set[str] = set()

    def claim(self, delivery_id: UUID, key: str) -> bool:
        if key in self._claimed:
            return False
        self._claimed.add(key)
        return True


def test_idempotency_guard_allows_one_claim() -> None:
    guard = IdempotencyGuard(_FakeIdempotencyRepo())
    delivery_id = uuid4()

    assert guard.claim(delivery_id) is True
    assert guard.claim(delivery_id) is False  # second claim blocked → no duplicate send
