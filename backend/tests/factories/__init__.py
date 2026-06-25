"""Entity factories writing via the SYNC session.

These let a story's tests fabricate cross-story data (users, contacts, templates, dispatches,
deliveries) without driving another story's endpoints. Each factory takes the sync ``sessionmaker``
(not a live ``Session``) and manages its own short transaction; they COMMIT, so the rows are visible
to a worker subprocess. Pair them with the ``truncate_notification_tables`` fixture for cleanup
(rows written this way cannot be rolled back from the API's transaction).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.persistence.models import (
    Contact,
    Delivery,
    DeliveryTransition,
    Dispatch,
    EmailToken,
    Template,
    TemplateRecipient,
    UserAccount,
)


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def make_user(
    session_factory: sessionmaker[Session],
    *,
    email: str | None = None,
    password_hash: str = "x-not-a-real-hash",
    is_verified: bool = True,
    is_admin: bool = False,
) -> UserAccount:
    user = UserAccount(
        email=(email or _unique_email()).lower(),
        password_hash=password_hash,
        is_verified=is_verified,
        is_admin=is_admin,
    )
    with session_factory() as session:
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
    return user


# The seeded test admin's known password — hashed with the real argon2 hasher so the login
# endpoint verifies it (T008). Distinct from the dev placeholder used by the migration seed.
ADMIN_TEST_PASSWORD = "admin-test-password"


def make_admin(
    session_factory: sessionmaker[Session],
    *,
    email: str = "admin@example.com",
    password: str = ADMIN_TEST_PASSWORD,
) -> UserAccount:
    """Seed a pre-verified admin with a real argon2 password hash (so it can log in via the API)."""
    from app.adapters.security.hasher import Argon2PasswordHasher

    return make_user(
        session_factory,
        email=email,
        password_hash=Argon2PasswordHasher().hash(password),
        is_verified=True,
        is_admin=True,
    )


def make_email_token(
    session_factory: sessionmaker[Session],
    *,
    user_id: uuid.UUID,
    purpose: str = "verify",
    token_hash: str = "token-hash",
    expires_at: datetime | None = None,
    consumed_at: datetime | None = None,
) -> EmailToken:
    token = EmailToken(
        user_id=user_id,
        purpose=purpose,
        token_hash=token_hash,
        expires_at=expires_at or (datetime.now(UTC) + timedelta(hours=24)),
        consumed_at=consumed_at,
    )
    with session_factory() as session:
        session.add(token)
        session.commit()
        session.refresh(token)
        session.expunge(token)
    return token


def make_contact(
    session_factory: sessionmaker[Session],
    *,
    owner_id: uuid.UUID,
    display_name: str = "Grace Hopper",
    email: str | None = "grace@example.com",
    phone: str | None = None,
    device_token: str | None = None,
) -> Contact:
    contact = Contact(
        owner_id=owner_id,
        display_name=display_name,
        email=email,
        phone=phone,
        device_token=device_token,
    )
    with session_factory() as session:
        session.add(contact)
        session.commit()
        session.refresh(contact)
        session.expunge(contact)
    return contact


def make_template(
    session_factory: sessionmaker[Session],
    *,
    owner_id: uuid.UUID,
    title: str = "Welcome",
    content: str = "Hello there!",
    channel: str = "email",
    recipient_ids: tuple[uuid.UUID, ...] = (),
) -> Template:
    template = Template(owner_id=owner_id, title=title, content=content, channel=channel)
    with session_factory() as session:
        session.add(template)
        session.flush()
        for contact_id in recipient_ids:
            session.add(TemplateRecipient(template_id=template.id, contact_id=contact_id))
        session.commit()
        session.refresh(template)
        session.expunge(template)
    return template


def make_dispatch(
    session_factory: sessionmaker[Session],
    *,
    user_id: uuid.UUID,
    channel: str = "email",
    title: str = "Welcome",
    content: str = "Hello there!",
) -> Dispatch:
    dispatch = Dispatch(user_id=user_id, channel=channel, title=title, content=content)
    with session_factory() as session:
        session.add(dispatch)
        session.commit()
        session.refresh(dispatch)
        session.expunge(dispatch)
    return dispatch


def make_sent_delivery(
    session_factory: sessionmaker[Session],
    *,
    user_id: uuid.UUID,
    at: datetime,
    channel: str = "email",
    destination: str = "grace@example.com",
    recipient_name: str = "Grace Hopper",
) -> Delivery:
    """A user-owned send that reached ``sent`` at an explicit UTC instant — the aggregation's unit.

    Writes one dispatch + one ``sent`` delivery + a ``to_status='sent'`` transition with the given
    ``at`` (the column's ``server_default now()`` is overridden) so the per-UTC-hour aggregation
    (data-model §3.1) sees a deterministic hour bucket (T027)."""
    dispatch = Dispatch(user_id=user_id, channel=channel, title="Seed", content="seed")
    with session_factory() as session:
        session.add(dispatch)
        session.flush()
        delivery = Delivery(
            dispatch_id=dispatch.id,
            recipient_name=recipient_name,
            destination=destination,
            status="sent",
        )
        session.add(delivery)
        session.flush()
        session.add(
            DeliveryTransition(
                delivery_id=delivery.id, from_status="queued", to_status="sent", at=at
            )
        )
        session.commit()
        session.refresh(delivery)
        session.expunge(delivery)
    return delivery


def make_delivery(
    session_factory: sessionmaker[Session],
    *,
    dispatch_id: uuid.UUID,
    recipient_name: str = "Grace Hopper",
    destination: str | None = "grace@example.com",
    contact_id: uuid.UUID | None = None,
    status: str = "queued",
    failure_reason: str | None = None,
    provider_ref: str | None = None,
) -> Delivery:
    delivery = Delivery(
        dispatch_id=dispatch_id,
        contact_id=contact_id,
        recipient_name=recipient_name,
        destination=destination,
        status=status,
        failure_reason=failure_reason,
        provider_ref=provider_ref,
    )
    with session_factory() as session:
        session.add(delivery)
        session.flush()
        # Mirror the real AsyncDispatchRepository.create_queued: record the initial append-only
        # transition (None → status) so seeded deliveries carry the same lifecycle history the
        # production flow writes (FR-025).
        session.add(
            DeliveryTransition(
                delivery_id=delivery.id,
                from_status=None,
                to_status=status,
            )
        )
        session.commit()
        session.refresh(delivery)
        session.expunge(delivery)
    return delivery
