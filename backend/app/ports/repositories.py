from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.accounts import EmailToken, TokenPurpose, UserAccount
from app.domain.channels import Channel
from app.domain.contacts import Contact
from app.domain.dispatch import Delivery, DeliveryStatus, Dispatch, Transition
from app.domain.templates import Template


class LivenessCompletionWriter(Protocol):
    """Synchronous writer used by Celery workers (psycopg engine)."""

    def record(self, correlation_id: UUID, pool_label: str) -> None: ...


class LivenessCompletionReader(Protocol):
    """Async reader used by the API / smoke CLI (asyncpg engine)."""

    async def completed_pools(self, correlation_id: UUID) -> set[str]: ...

    async def both_completed(self, correlation_id: UUID) -> bool: ...


@dataclass(frozen=True, slots=True)
class AuthRecord:
    """Login lookup result: identity + the stored hash. Kept at the repository boundary so the
    password hash never enters the domain layer (data-model)."""

    id: UUID
    email: str
    is_verified: bool
    password_hash: str


class AccountRepository(Protocol):
    """Async user-account persistence (API path)."""

    async def email_exists(self, email: str) -> bool: ...

    async def create(self, email: str, password_hash: str) -> UserAccount: ...

    async def get_by_id(self, user_id: UUID) -> UserAccount | None: ...

    async def get_auth_by_email(self, email: str) -> AuthRecord | None: ...

    async def set_verified(self, user_id: UUID) -> None: ...

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None: ...


class EmailTokenRepository(Protocol):
    """Async verification/reset-token persistence (API path)."""

    async def create(
        self,
        *,
        user_id: UUID,
        purpose: TokenPurpose,
        token_hash: str,
        expires_at: datetime,
    ) -> EmailToken: ...

    async def get_by_hash(self, token_hash: str, purpose: TokenPurpose) -> EmailToken | None: ...

    async def mark_consumed(self, token_id: UUID, consumed_at: datetime) -> None: ...


class ContactRepository(Protocol):
    """Async contacts persistence — every query is scoped to the owner (FR-010, SC-003)."""

    async def add(
        self,
        *,
        owner_id: UUID,
        display_name: str,
        email: str | None,
        phone: str | None,
        device_token: str | None,
    ) -> Contact: ...

    async def list_for_owner(self, owner_id: UUID, *, limit: int, offset: int) -> list[Contact]: ...

    async def get_many_for_owner(self, owner_id: UUID, contact_ids: list[UUID]) -> list[Contact]:
        """Return the owner's contacts among ``contact_ids`` (recipient snapshots for a send)."""
        ...

    async def owned_ids(self, owner_id: UUID, contact_ids: list[UUID]) -> set[UUID]:
        """Return the subset of ``contact_ids`` actually owned by ``owner_id`` (recipient-ownership
        checks for templates, FR-011)."""
        ...


class TemplateRepository(Protocol):
    """Async template persistence (incl. the recipient association); owner-scoped CRUD."""

    async def create(
        self,
        owner_id: UUID,
        *,
        title: str,
        content: str,
        channel: Channel,
        recipient_ids: list[UUID],
    ) -> Template: ...

    async def list_for_owner(
        self, owner_id: UUID, *, limit: int, offset: int
    ) -> list[Template]: ...

    async def get_for_owner(self, owner_id: UUID, template_id: UUID) -> Template | None: ...

    async def update(
        self,
        owner_id: UUID,
        template_id: UUID,
        *,
        title: str,
        content: str,
        channel: Channel,
        recipient_ids: list[UUID],
    ) -> Template | None:
        """Update an owned template (replacing its recipient set). ``None`` if not found/owned."""
        ...

    async def delete(self, owner_id: UUID, template_id: UUID) -> bool:
        """Delete an owned template; ``True`` if a row was removed, else ``False``."""
        ...


# --- Dispatch / delivery lifecycle (US3) ----------------------------------------------------------


class DispatchRepository(Protocol):
    """Async dispatch persistence (API path): snapshot creation + owner-scoped status reads."""

    async def create(
        self, user_id: UUID, *, channel: Channel, title: str, content: str
    ) -> Dispatch: ...

    async def list_for_owner(self, user_id: UUID, *, limit: int, offset: int) -> list[Dispatch]: ...

    async def get_for_owner(self, user_id: UUID, dispatch_id: UUID) -> Dispatch | None: ...


class DeliveryRepository(Protocol):
    """Async delivery persistence (API path): create queued rows on fan-out, read status, and
    apply webhook confirmations."""

    async def create_queued(
        self,
        dispatch_id: UUID,
        *,
        contact_id: UUID | None,
        recipient_name: str,
        destination: str | None,
    ) -> Delivery: ...

    async def list_for_dispatch(self, dispatch_id: UUID) -> list[Delivery]: ...

    async def transitions_for_delivery(self, delivery_id: UUID) -> list[Transition]: ...

    async def confirm_by_provider_ref(
        self, provider_ref: str, outcome: DeliveryStatus, reason: str | None
    ) -> bool:
        """Apply a webhook confirmation: ``sent → delivered|failed`` for the delivery matching
        ``provider_ref``. Idempotent and correlation-guarded — returns ``False`` (no state change)
        for an unknown ref or a delivery not currently ``sent`` (FR-025/FR-031)."""
        ...


class SyncDispatchReader(Protocol):
    """Sync dispatch reads used by Celery workers (psycopg engine)."""

    def get(self, dispatch_id: UUID) -> Dispatch | None: ...


class SyncDeliveryRepository(Protocol):
    """Sync delivery writes used by Celery workers (psycopg engine); append-only transitions."""

    def get(self, delivery_id: UUID) -> Delivery | None: ...

    def queued_ids_for_dispatch(self, dispatch_id: UUID) -> list[UUID]: ...

    def record_sent(self, delivery_id: UUID, *, provider_ref: str, attempt: int | None) -> None: ...

    def record_failed(self, delivery_id: UUID, *, reason: str, attempt: int | None) -> None: ...

    def confirm(self, delivery_id: UUID, *, outcome: DeliveryStatus, reason: str | None) -> bool:
        """Apply a poll confirmation: ``sent → delivered|failed``. ``False`` if not ``sent``."""
        ...


class IdempotencyKeyRepository(Protocol):
    """Sync idempotency-claim persistence used by Celery workers (psycopg engine)."""

    def claim(self, delivery_id: UUID, key: str) -> bool:
        """Insert the claim. ``True`` if newly claimed, ``False`` if it already existed (a prior
        attempt already delivered → caller must not send again)."""
        ...
