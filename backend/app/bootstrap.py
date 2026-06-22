from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.adapters.channels.email import SimulatedEmailChannel
from app.adapters.channels.provider_http import ProviderClient
from app.adapters.channels.push import SimulatedPushChannel
from app.adapters.channels.sms import SimulatedSmsChannel
from app.adapters.mailer.smtp import SmtpMailer
from app.adapters.persistence.async_repo import (
    AsyncAccountRepository,
    AsyncContactRepository,
    AsyncDeliveryRepository,
    AsyncDispatchRepository,
    AsyncEmailTokenRepository,
    AsyncTemplateRepository,
)
from app.adapters.probes.celery_broker import CeleryBrokerProbe
from app.adapters.probes.celery_worker import CeleryWorkerProbe
from app.adapters.probes.data_store import AsyncDataStoreProbe
from app.adapters.security.hasher import Argon2PasswordHasher
from app.adapters.security.jwt import PyJwtTokenService
from app.application.accounts import AccountsService
from app.application.confirmation import WebhookConfirmationService
from app.application.contacts import ContactsService
from app.application.liveness import LivenessService, ReadinessService
from app.application.readiness_aggregate import AggregateReadinessService
from app.application.sending import SendingService, SendQueryService
from app.application.templates import TemplatesService
from app.domain.channels import Channel
from app.infra.db.async_engine import get_async_sessionmaker
from app.ports.channels import ChannelPort
from app.ports.clock import Clock, SystemClock
from app.ports.mailer import Mailer
from app.ports.security import TokenService
from app.settings import Settings, get_settings
from app.tasks.celery_app import celery_app


def build_channel_registry(settings: Settings) -> dict[Channel, ChannelPort]:
    """The Open/Closed channel seam: one adapter per channel behind a shared provider client. Adding
    a channel adds a line here and nothing else (FR-028 / SC-008)."""
    provider = ProviderClient(settings.provider_base_url)
    callback = settings.webhook_callback_url
    return {
        Channel.EMAIL: SimulatedEmailChannel(provider, callback),
        Channel.SMS: SimulatedSmsChannel(provider),
        Channel.PUSH: SimulatedPushChannel(provider, callback),
    }


def _default_enqueue(dispatch_id: UUID) -> None:
    from app.tasks.sending import dispatch_fanout

    dispatch_fanout.apply_async(args=[str(dispatch_id)], queue="io")


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    liveness: LivenessService
    readiness: ReadinessService
    aggregate: AggregateReadinessService
    token_service: TokenService
    accounts: AccountsService
    contacts: ContactsService
    templates: TemplatesService
    channels: dict[Channel, ChannelPort]
    sending: SendingService
    send_query: SendQueryService
    confirmation: WebhookConfirmationService


def build_container(
    *,
    mailer: Mailer | None = None,
    clock: Clock | None = None,
    enqueue: Callable[[UUID], None] | None = None,
) -> Container:
    """Composition root: bind ports → adapters.

    ``mailer``/``clock``/``enqueue`` are injectable so tests can supply a fake mailer (no SMTP), a
    fixed clock (deterministic expiry), and a captured/no-op enqueue (no broker publish).
    """
    settings = get_settings()
    session_factory = get_async_sessionmaker()
    clock = clock or SystemClock()
    enqueue = enqueue or _default_enqueue

    data_store = AsyncDataStoreProbe(session_factory)
    broker = CeleryBrokerProbe(celery_app, settings.readiness_check_timeout_s)
    worker = CeleryWorkerProbe(celery_app, settings.worker_ping_timeout_s)

    hasher = Argon2PasswordHasher()
    token_service = PyJwtTokenService(
        secret=settings.jwt_secret,
        algorithm=settings.jwt_alg,
        access_ttl_min=settings.access_token_ttl_min,
        clock=clock,
    )
    accounts = AccountsService(
        accounts=AsyncAccountRepository(session_factory),
        tokens=AsyncEmailTokenRepository(session_factory),
        hasher=hasher,
        token_service=token_service,
        mailer=mailer or SmtpMailer(settings),
        clock=clock,
        settings=settings,
    )

    contact_repo = AsyncContactRepository(session_factory)
    contacts = ContactsService(contact_repo)
    templates = TemplatesService(AsyncTemplateRepository(session_factory), contact_repo)

    channels = build_channel_registry(settings)
    dispatch_repo = AsyncDispatchRepository(session_factory)
    delivery_repo = AsyncDeliveryRepository(session_factory)
    sending = SendingService(
        templates=AsyncTemplateRepository(session_factory),
        contacts=contact_repo,
        dispatches=dispatch_repo,
        deliveries=delivery_repo,
        channels=channels,
        enqueue=enqueue,
    )
    send_query = SendQueryService(dispatches=dispatch_repo, deliveries=delivery_repo)
    confirmation = WebhookConfirmationService(delivery_repo)

    return Container(
        settings=settings,
        liveness=LivenessService(),
        readiness=ReadinessService(data_store),
        aggregate=AggregateReadinessService(
            data_store, broker, worker, settings.readiness_check_timeout_s
        ),
        token_service=token_service,
        accounts=accounts,
        contacts=contacts,
        templates=templates,
        channels=channels,
        sending=sending,
        send_query=send_query,
        confirmation=confirmation,
    )
