# Internal Contract: `ChannelPort` (the Open/Closed seam)

This is the single strategy interface every channel implements. Per constitution Principle II and
FR-028 / SC-008: **adding a channel = adding ONE adapter that implements this port + binding it in
`bootstrap.py`. No existing channel adapter and no shared dispatch/resilience code may change.**

Location: `backend/app/ports/channels.py` (Protocol). Adapters: `backend/app/adapters/channels/<name>/`.

## Port

```python
class ChannelPort(Protocol):
    channel: Channel  # EMAIL | SMS | PUSH

    def destination_of(self, contact: ContactSnapshot) -> str | None:
        """Return the channel-relevant destination, or None if absent (→ failed: missing_destination)."""

    def validate(self, destination: str, payload: Payload) -> None:
        """Channel pre-send validation. Raise ChannelValidationError(reason) to fail before 'sent'
        (email: format; push: device-token; sms: length already enforced at template save)."""

    def send(self, destination: str, payload: Payload, idempotency_key: str) -> SendResult:
        """Hand the message to the provider over HTTP. Returns SendResult(provider_ref) on accept;
        raises TransientChannelError (429/timeout/5xx) to drive retry/backoff/breaker, or
        PermanentChannelError(reason) to fail. MUST be idempotent w.r.t. idempotency_key."""

    def confirmation_mode(self) -> ConfirmationMode:
        """WEBHOOK (email/push) or POLL (sms) — tells the dispatcher how the terminal outcome arrives."""

    def poll_status(self, provider_ref: str) -> PollOutcome:
        """POLL channels only: query provider status → DELIVERED | FAILED(reason) | PENDING."""
```

## Rules the dispatcher (in `application/`) guarantees — NOT the adapter

- Retry with exponential backoff (**tenacity**) around `send`.
- Circuit breaker per **channel/destination** (**pybreaker**).
- Idempotency claim (hand-rolled, persisted unique key) before `send`.
- Lifecycle transitions (`queued → sent → delivered | failed`) persisted append-only.
- Correlation of webhook/poll confirmations back to the delivery via `provider_ref`.

The adapter ONLY: selects the destination, validates, forwards to the provider over HTTP (simulating
nothing itself beyond what the provider injects), and reports status. It contains **no** retry, breaker,
idempotency, or persistence logic (constitution Principle IV; CLAUDE.md "Adapters simulate failure …
resilience lives in application/").

## Adding a 4th channel (worked example for SC-008 verification)

1. `adapters/channels/slack/__init__.py` → `SimulatedSlackChannel(ChannelPort)`.
2. Bind it in `bootstrap.py`'s channel registry keyed by `Channel.SLACK`.
3. Add `SLACK` to the `Channel` enum + DB `CHECK` (a new migration).
   → Zero edits to email/sms/push adapters or the dispatch/resilience flow. A test asserts the registry
   resolves all channels and that the dispatcher imports no concrete channel module.
