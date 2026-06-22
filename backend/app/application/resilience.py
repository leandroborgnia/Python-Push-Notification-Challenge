from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar
from uuid import UUID

from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.domain.errors import TransientChannelError
from app.ports.repositories import IdempotencyKeyRepository

T = TypeVar("T")


class CircuitBreaker(Protocol):
    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any: ...


class BreakerRegistry(Protocol):
    def get(self, key: str) -> CircuitBreaker: ...


class ResiliencePolicy:
    """Wraps an outbound send with retry+backoff (tenacity) around a per-key circuit breaker
    (pybreaker). Framework-free and adapter-free — the breaker is injected as a port so the policy
    is unit-testable with a fake (research §6). Lives in ``application/``; adapters stay dumb."""

    def __init__(
        self, *, breakers: BreakerRegistry, max_attempts: int, backoff_base_s: float
    ) -> None:
        self._breakers = breakers
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s

    def run(self, key: str, func: Callable[[], T]) -> T:
        """Run ``func`` under the breaker for ``key``, retrying transient failures with exponential
        backoff + jitter. Re-raises the last error once attempts are exhausted; a breaker-open error
        (not a transient error) is NOT retried and propagates immediately."""
        breaker = self._breakers.get(key)
        retrying: Retrying = Retrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_random_exponential(multiplier=self._backoff_base_s, max=10),
            retry=retry_if_exception_type(TransientChannelError),
            reraise=True,
        )
        result: T = retrying(lambda: breaker.call(func))
        return result


class IdempotencyGuard:
    """Hand-rolled idempotency: claim a deterministic key before the channel call. A failed claim
    (unique violation) means a prior attempt already delivered → caller must skip the send
    (FR-024/FR-026, SC-007)."""

    def __init__(self, repository: IdempotencyKeyRepository) -> None:
        self._repository = repository

    @staticmethod
    def key_for(delivery_id: UUID) -> str:
        # Scoped to one delivery (= one dispatch+recipient), never across sends.
        return f"delivery:{delivery_id}"

    def claim(self, delivery_id: UUID) -> bool:
        return self._repository.claim(delivery_id, self.key_for(delivery_id))
