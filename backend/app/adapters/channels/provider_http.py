from __future__ import annotations

from typing import Any

import httpx

from app.domain.errors import PermanentChannelError, TransientChannelError


class ProviderClient:
    """Shared SYNC HTTP client to the simulated provider (the worker is thread-pooled; httpx.Client
    is thread-safe for requests). Translates provider failure modes into channel errors so the
    resilience layer can react. respx-mockable in tests."""

    def __init__(self, base_url: str, *, timeout: float = 5.0) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def send(
        self,
        *,
        channel: str,
        destination: str,
        payload: dict[str, Any],
        idempotency_key: str,
        callback_url: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "channel": channel,
            "destination": destination,
            "payload": payload,
            "idempotency_key": idempotency_key,
        }
        if callback_url:
            body["callback_url"] = callback_url
        try:
            response = self._client.post("/send", json=body)
        except httpx.TimeoutException as exc:
            raise TransientChannelError("provider timeout") from exc
        except httpx.HTTPError as exc:
            raise TransientChannelError(f"provider connection error: {exc}") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientChannelError(f"provider returned {response.status_code}")
        if response.status_code >= 400:
            raise PermanentChannelError(f"provider rejected the send ({response.status_code})")
        provider_ref = response.json()["provider_ref"]
        return str(provider_ref)

    def sms_status(self, provider_ref: str) -> tuple[str, str | None]:
        try:
            response = self._client.get(f"/sms/{provider_ref}/status")
        except httpx.TimeoutException as exc:
            raise TransientChannelError("provider timeout") from exc
        except httpx.HTTPError as exc:
            raise TransientChannelError(f"provider connection error: {exc}") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientChannelError(f"provider returned {response.status_code}")
        if response.status_code == 404:
            raise PermanentChannelError("unknown provider_ref")
        data = response.json()
        return str(data["status"]), data.get("reason")
