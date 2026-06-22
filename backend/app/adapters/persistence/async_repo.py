from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence import models
from app.adapters.persistence.models import LivenessCompletion
from app.domain.accounts import EmailToken, TokenPurpose, UserAccount
from app.domain.channels import Channel
from app.domain.contacts import Contact
from app.domain.dispatch import Delivery, DeliveryStatus, Dispatch, Transition
from app.domain.templates import Template
from app.ports.repositories import AuthRecord

_REQUIRED_POOLS = frozenset({"cpu", "io"})


class AsyncLivenessCompletionReader:
    """Implements LivenessCompletionReader using the async (asyncpg) engine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def completed_pools(self, correlation_id: UUID) -> set[str]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(LivenessCompletion.pool_label).where(
                    LivenessCompletion.correlation_id == correlation_id
                )
            )
            return set(result.scalars().all())

    async def both_completed(self, correlation_id: UUID) -> bool:
        return await self.completed_pools(correlation_id) >= _REQUIRED_POOLS


def _to_user(row: models.UserAccount) -> UserAccount:
    return UserAccount(id=row.id, email=row.email, is_verified=row.is_verified)


def _to_token(row: models.EmailToken) -> EmailToken:
    return EmailToken(
        id=row.id,
        user_id=row.user_id,
        purpose=TokenPurpose(row.purpose),
        expires_at=row.expires_at,
        consumed_at=row.consumed_at,
    )


def _to_contact(row: models.Contact) -> Contact:
    return Contact(
        id=row.id,
        owner_id=row.owner_id,
        display_name=row.display_name,
        email=row.email,
        phone=row.phone,
        device_token=row.device_token,
    )


class AsyncAccountRepository:
    """Implements AccountRepository using the async (asyncpg) engine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def email_exists(self, email: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.UserAccount.id).where(
                    func.lower(models.UserAccount.email) == email.lower()
                )
            )
            return result.first() is not None

    async def create(self, email: str, password_hash: str) -> UserAccount:
        async with self._session_factory() as session:
            row = models.UserAccount(
                email=email.lower(), password_hash=password_hash, is_verified=False
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_user(row)

    async def get_by_id(self, user_id: UUID) -> UserAccount | None:
        async with self._session_factory() as session:
            row = await session.get(models.UserAccount, user_id)
            return _to_user(row) if row is not None else None

    async def get_auth_by_email(self, email: str) -> AuthRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.UserAccount).where(
                    func.lower(models.UserAccount.email) == email.lower()
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return AuthRecord(
                id=row.id,
                email=row.email,
                is_verified=row.is_verified,
                password_hash=row.password_hash,
            )

    async def set_verified(self, user_id: UUID) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.UserAccount)
                .where(models.UserAccount.id == user_id)
                .values(is_verified=True)
            )
            await session.commit()

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.UserAccount)
                .where(models.UserAccount.id == user_id)
                .values(password_hash=password_hash)
            )
            await session.commit()


class AsyncEmailTokenRepository:
    """Implements EmailTokenRepository using the async (asyncpg) engine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        user_id: UUID,
        purpose: TokenPurpose,
        token_hash: str,
        expires_at: datetime,
    ) -> EmailToken:
        async with self._session_factory() as session:
            row = models.EmailToken(
                user_id=user_id,
                purpose=purpose.value,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_token(row)

    async def get_by_hash(self, token_hash: str, purpose: TokenPurpose) -> EmailToken | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.EmailToken).where(
                    models.EmailToken.token_hash == token_hash,
                    models.EmailToken.purpose == purpose.value,
                )
            )
            row = result.scalar_one_or_none()
            return _to_token(row) if row is not None else None

    async def mark_consumed(self, token_id: UUID, consumed_at: datetime) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.EmailToken)
                .where(models.EmailToken.id == token_id)
                .values(consumed_at=consumed_at)
            )
            await session.commit()


class AsyncContactRepository:
    """Implements ContactRepository using the async (asyncpg) engine; owner-scoped queries."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(
        self,
        *,
        owner_id: UUID,
        display_name: str,
        email: str | None,
        phone: str | None,
        device_token: str | None,
    ) -> Contact:
        async with self._session_factory() as session:
            row = models.Contact(
                owner_id=owner_id,
                display_name=display_name,
                email=email,
                phone=phone,
                device_token=device_token,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_contact(row)

    async def list_for_owner(self, owner_id: UUID, *, limit: int, offset: int) -> list[Contact]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.Contact)
                .where(models.Contact.owner_id == owner_id)
                .order_by(models.Contact.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return [_to_contact(row) for row in result.scalars().all()]

    async def get_many_for_owner(self, owner_id: UUID, contact_ids: list[UUID]) -> list[Contact]:
        if not contact_ids:
            return []
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.Contact).where(
                    models.Contact.owner_id == owner_id,
                    models.Contact.id.in_(contact_ids),
                )
            )
            return [_to_contact(row) for row in result.scalars().all()]

    async def owned_ids(self, owner_id: UUID, contact_ids: list[UUID]) -> set[UUID]:
        if not contact_ids:
            return set()
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.Contact.id).where(
                    models.Contact.owner_id == owner_id,
                    models.Contact.id.in_(contact_ids),
                )
            )
            return set(result.scalars().all())


def _to_template(row: models.Template, recipient_ids: tuple[UUID, ...]) -> Template:
    return Template(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        content=row.content,
        channel=Channel(row.channel),
        recipient_ids=recipient_ids,
    )


class AsyncTemplateRepository:
    """Implements TemplateRepository (incl. template_recipient writes); owner-scoped CRUD."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        owner_id: UUID,
        *,
        title: str,
        content: str,
        channel: Channel,
        recipient_ids: list[UUID],
    ) -> Template:
        async with self._session_factory() as session:
            row = models.Template(
                owner_id=owner_id, title=title, content=content, channel=channel.value
            )
            session.add(row)
            await session.flush()
            for contact_id in recipient_ids:
                session.add(models.TemplateRecipient(template_id=row.id, contact_id=contact_id))
            await session.commit()
            await session.refresh(row)
            return _to_template(row, tuple(recipient_ids))

    async def list_for_owner(self, owner_id: UUID, *, limit: int, offset: int) -> list[Template]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.Template)
                .where(models.Template.owner_id == owner_id)
                .order_by(models.Template.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = list(result.scalars().all())
            recipients: dict[UUID, list[UUID]] = defaultdict(list)
            template_ids = [row.id for row in rows]
            if template_ids:
                assoc = await session.execute(
                    select(
                        models.TemplateRecipient.template_id,
                        models.TemplateRecipient.contact_id,
                    ).where(models.TemplateRecipient.template_id.in_(template_ids))
                )
                for template_id, contact_id in assoc.all():
                    recipients[template_id].append(contact_id)
            return [_to_template(row, tuple(recipients[row.id])) for row in rows]

    async def get_for_owner(self, owner_id: UUID, template_id: UUID) -> Template | None:
        async with self._session_factory() as session:
            row = await session.get(models.Template, template_id)
            if row is None or row.owner_id != owner_id:
                return None
            recipient_ids = await self._recipient_ids(session, template_id)
            return _to_template(row, recipient_ids)

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
        async with self._session_factory() as session:
            row = await session.get(models.Template, template_id)
            if row is None or row.owner_id != owner_id:
                return None
            row.title = title
            row.content = content
            row.channel = channel.value
            await session.execute(
                delete(models.TemplateRecipient).where(
                    models.TemplateRecipient.template_id == template_id
                )
            )
            for contact_id in recipient_ids:
                session.add(
                    models.TemplateRecipient(template_id=template_id, contact_id=contact_id)
                )
            await session.commit()
            await session.refresh(row)
            return _to_template(row, tuple(recipient_ids))

    async def delete(self, owner_id: UUID, template_id: UUID) -> bool:
        async with self._session_factory() as session:
            row = await session.get(models.Template, template_id)
            if row is None or row.owner_id != owner_id:
                return False
            await session.delete(row)  # template_recipient rows cascade at the DB (FK ON DELETE)
            await session.commit()
            return True

    @staticmethod
    async def _recipient_ids(session: AsyncSession, template_id: UUID) -> tuple[UUID, ...]:
        result = await session.execute(
            select(models.TemplateRecipient.contact_id).where(
                models.TemplateRecipient.template_id == template_id
            )
        )
        return tuple(result.scalars().all())


def _to_dispatch(row: models.Dispatch) -> Dispatch:
    return Dispatch(
        id=row.id,
        user_id=row.user_id,
        channel=Channel(row.channel),
        title=row.title,
        content=row.content,
        created_at=row.created_at,
    )


def _to_delivery(row: models.Delivery) -> Delivery:
    return Delivery(
        id=row.id,
        dispatch_id=row.dispatch_id,
        recipient_name=row.recipient_name,
        status=DeliveryStatus(row.status),
        destination=row.destination,
        failure_reason=row.failure_reason,
        provider_ref=row.provider_ref,
        contact_id=row.contact_id,
    )


def _to_transition(row: models.DeliveryTransition) -> Transition:
    return Transition(
        from_status=DeliveryStatus(row.from_status) if row.from_status else None,
        to_status=DeliveryStatus(row.to_status),
        reason=row.reason,
        attempt=row.attempt,
        at=row.at,
    )


class AsyncDispatchRepository:
    """Implements DispatchRepository using the async (asyncpg) engine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self, user_id: UUID, *, channel: Channel, title: str, content: str
    ) -> Dispatch:
        async with self._session_factory() as session:
            row = models.Dispatch(
                user_id=user_id, channel=channel.value, title=title, content=content
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_dispatch(row)

    async def list_for_owner(self, user_id: UUID, *, limit: int, offset: int) -> list[Dispatch]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.Dispatch)
                .where(models.Dispatch.user_id == user_id)
                .order_by(models.Dispatch.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return [_to_dispatch(row) for row in result.scalars().all()]

    async def get_for_owner(self, user_id: UUID, dispatch_id: UUID) -> Dispatch | None:
        async with self._session_factory() as session:
            row = await session.get(models.Dispatch, dispatch_id)
            if row is None or row.user_id != user_id:
                return None
            return _to_dispatch(row)


class AsyncDeliveryRepository:
    """Implements DeliveryRepository using the async (asyncpg) engine (API + webhook path)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_queued(
        self,
        dispatch_id: UUID,
        *,
        contact_id: UUID | None,
        recipient_name: str,
        destination: str | None,
    ) -> Delivery:
        async with self._session_factory() as session:
            row = models.Delivery(
                dispatch_id=dispatch_id,
                contact_id=contact_id,
                recipient_name=recipient_name,
                destination=destination,
                status=DeliveryStatus.QUEUED.value,
            )
            session.add(row)
            await session.flush()
            session.add(
                models.DeliveryTransition(
                    delivery_id=row.id,
                    from_status=None,
                    to_status=DeliveryStatus.QUEUED.value,
                )
            )
            await session.commit()
            await session.refresh(row)
            return _to_delivery(row)

    async def list_for_dispatch(self, dispatch_id: UUID) -> list[Delivery]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.Delivery)
                .where(models.Delivery.dispatch_id == dispatch_id)
                .order_by(models.Delivery.created_at)
            )
            return [_to_delivery(row) for row in result.scalars().all()]

    async def transitions_for_delivery(self, delivery_id: UUID) -> list[Transition]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.DeliveryTransition)
                .where(models.DeliveryTransition.delivery_id == delivery_id)
                .order_by(models.DeliveryTransition.at, models.DeliveryTransition.id)
            )
            return [_to_transition(row) for row in result.scalars().all()]

    async def confirm_by_provider_ref(
        self, provider_ref: str, outcome: DeliveryStatus, reason: str | None
    ) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(models.Delivery).where(
                    models.Delivery.provider_ref == provider_ref,
                    models.Delivery.status == DeliveryStatus.SENT.value,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return False  # unknown ref or not currently 'sent' → ignore (idempotent)
            row.status = outcome.value
            if outcome is DeliveryStatus.FAILED:
                row.failure_reason = reason
            session.add(
                models.DeliveryTransition(
                    delivery_id=row.id,
                    from_status=DeliveryStatus.SENT.value,
                    to_status=outcome.value,
                    reason=reason,
                )
            )
            await session.commit()
            return True
