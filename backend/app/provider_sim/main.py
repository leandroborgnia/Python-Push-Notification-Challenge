"""In-repo simulated channel provider (deployed as its own workload from the same image).

Our channel adapters call it over HTTP. It injects the constitution-mandated failure modes
(latency / random error / 429 / timeout) and drives asynchronous confirmation: email/push get a
delayed webhook callback; SMS exposes a status endpoint we poll. Failure rates default to 0 so the
real-worker routing round-trip is deterministic; respx covers failure injection in-process.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = structlog.get_logger("app.provider_sim")


class ProviderSimSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROVIDER_SIM_", extra="ignore")

    latency_ms: int = 0
    rate_limit_rate: float = 0.0  # → 429 (drives retry/backoff + breaker)
    error_rate: float = 0.0  # → 500
    timeout_rate: float = 0.0  # → 504
    fail_rate: float = 0.0  # terminal outcome = failed (else delivered)
    callback_delay_s: float = 0.0


class SendRequest(BaseModel):
    channel: str
    destination: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    callback_url: str | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_app() -> FastAPI:
    settings = ProviderSimSettings()
    sms_status: dict[str, dict[str, str | None]] = {}
    app = FastAPI(title="Simulated Channel Provider")

    async def _post_callback(url: str, provider_ref: str, outcome: str) -> None:
        if settings.callback_delay_s:
            await asyncio.sleep(settings.callback_delay_s)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, json={"provider_ref": provider_ref, "outcome": outcome})
        except httpx.HTTPError as exc:  # best-effort; a missing app must not crash the provider
            _log.info("callback_failed", url=url, error=str(exc))

    @app.post("/send", status_code=status.HTTP_202_ACCEPTED)
    async def send(body: SendRequest, background: BackgroundTasks) -> dict[str, str]:
        if settings.latency_ms:
            await asyncio.sleep(settings.latency_ms / 1000)
        roll = random.random()
        if roll < settings.rate_limit_rate:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        if roll < settings.rate_limit_rate + settings.error_rate:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        if roll < settings.rate_limit_rate + settings.error_rate + settings.timeout_rate:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT)

        provider_ref = uuid.uuid4().hex
        delivered = random.random() >= settings.fail_rate
        outcome = "delivered" if delivered else "failed"
        if body.channel == "sms":
            sms_status[provider_ref] = {
                "status": outcome,
                "reason": None if delivered else "carrier_rejected",
            }
        elif body.callback_url:
            background.add_task(_post_callback, body.callback_url, provider_ref, outcome)
        return {"provider_ref": provider_ref, "accepted_at": _now_iso()}

    @app.get("/sms/{provider_ref}/status")
    async def sms_status_endpoint(provider_ref: str) -> dict[str, str | None]:
        record = sms_status.get(provider_ref)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return {"provider_ref": provider_ref, **record}

    return app


app = create_app()
