from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
import pytest_asyncio

from tests.fakes import FakeMailer

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient

# Child-first order is unnecessary with CASCADE, but keep it explicit for readability.
_NOTIFICATION_TABLES = (
    "idempotency_key",
    "delivery_transition",
    "delivery",
    "dispatch",
    "template_recipient",
    "template",
    "contact",
    "email_token",
    "user_account",
)

_RABBITMQ_CONF = Path(__file__).resolve().parent / "fixtures" / "permit-deprecated.conf"

# Base images pinned to explicit patch version + digest (constitution Principle I).
_POSTGRES_IMAGE = (
    "postgres:16.14-alpine@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"  # noqa: E501
)
_RABBITMQ_IMAGE = (
    "rabbitmq:4.3.2-alpine@sha256:8489bba72d91465b2ed422394966d270858252844cc7bd91dfb8ab3dd43fdaea"  # noqa: E501
)

# Worker pool per platform: Celery prefork doesn't run on Windows, so use solo locally;
# CI (Linux) uses the production pool types. Routing + the sync/async seam are what these
# tests prove, not the pool implementation.
_IS_WINDOWS = sys.platform.startswith("win")
_CPU_POOL = "solo" if _IS_WINDOWS else "prefork"
_IO_POOL = "solo" if _IS_WINDOWS else "threads"


def _reset_runtime(async_url: str, sync_url: str, broker_url: str) -> None:
    os.environ["DATABASE_URL_ASYNC"] = async_url
    os.environ["DATABASE_URL_SYNC"] = sync_url
    os.environ["BROKER_URL"] = broker_url

    from app.infra.db import async_engine, sync_engine
    from app.settings import get_settings

    get_settings.cache_clear()
    async_engine._engine = None
    async_engine._sessionmaker = None
    sync_engine._engine = None
    sync_engine._sessionmaker = None

    from app.tasks.celery_app import celery_app

    celery_app.conf.broker_url = broker_url


@pytest.fixture(scope="session")
def container_urls() -> Iterator[tuple[str, str, str]]:
    """Start ephemeral Postgres + RabbitMQ; yield (async_url, sync_url, broker_url)."""
    from testcontainers.postgres import PostgresContainer
    from testcontainers.rabbitmq import RabbitMqContainer

    rabbitmq = RabbitMqContainer(_RABBITMQ_IMAGE).with_volume_mapping(
        str(_RABBITMQ_CONF), "/etc/rabbitmq/conf.d/10-permit-deprecated.conf", "ro"
    )
    with (
        PostgresContainer(_POSTGRES_IMAGE) as pg,
        rabbitmq as mq,
    ):
        base = pg.get_connection_url()  # postgresql+psycopg2://user:pass@host:port/db
        sync_url = base.replace("+psycopg2", "+psycopg")
        async_url = base.replace("+psycopg2", "+asyncpg")
        host = mq.get_container_host_ip()
        port = mq.get_exposed_port(5672)
        broker_url = f"amqp://guest:guest@{host}:{port}//"
        yield async_url, sync_url, broker_url


@pytest.fixture(scope="session")
def migrated_db(container_urls: tuple[str, str, str]) -> tuple[str, str, str]:
    """Apply the schema via the ORM metadata (mirrors the Alembic migration)."""
    async_url, sync_url, broker_url = container_urls
    _reset_runtime(async_url, sync_url, broker_url)

    from sqlalchemy import create_engine

    from app.adapters.persistence.models import Base

    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return container_urls


@pytest.fixture
def app(migrated_db: tuple[str, str, str]) -> Iterator[FastAPI]:
    async_url, sync_url, broker_url = migrated_db
    _reset_runtime(async_url, sync_url, broker_url)
    from app.main import create_app

    yield create_app()


@pytest.fixture
def truncate_completions(migrated_db: tuple[str, str, str]) -> Iterator[None]:
    """Truncation cleanup — transaction rollback cannot span a worker's own connection."""
    yield
    from sqlalchemy import create_engine, text

    engine = create_engine(migrated_db[1])
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE liveness_completion"))
    engine.dispose()


@pytest.fixture
def truncate_notification_tables(migrated_db: tuple[str, str, str]) -> Iterator[None]:
    """Truncate all 003 tables — for tests whose rows are written by a worker subprocess (or a
    committing client) and therefore cannot be cleaned by transaction rollback."""
    yield
    from sqlalchemy import create_engine, text

    engine = create_engine(migrated_db[1])
    with engine.begin() as conn:
        conn.execute(
            text(f"TRUNCATE TABLE {', '.join(_NOTIFICATION_TABLES)} RESTART IDENTITY CASCADE")
        )
    engine.dispose()


@pytest.fixture
def fake_mailer() -> FakeMailer:
    """A captured-token mailer bound into the test app (no real SMTP in the suite)."""
    return FakeMailer()


@pytest.fixture
def enqueue_calls() -> list[UUID]:
    """Captures dispatch fan-out enqueues so the rollback client never publishes to the broker."""
    return []


@pytest_asyncio.fixture
async def client(
    migrated_db: tuple[str, str, str], fake_mailer: FakeMailer, enqueue_calls: list[UUID]
) -> AsyncIterator[AsyncClient]:
    """Unauthenticated ``httpx.AsyncClient`` with transaction-rollback isolation (constitution V):
    a single shared async connection holds the outer transaction and the app's sessions join it via
    per-session SAVEPOINTs, so every write in a test rolls back at teardown. Tests that read DB
    state can call ``get_async_sessionmaker()`` to get this same bound, in-transaction factory.

    Fan-out is captured into ``enqueue_calls`` rather than published to the broker (no worker)."""
    async_url, sync_url, broker_url = migrated_db
    _reset_runtime(async_url, sync_url, broker_url)

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.bootstrap import build_container
    from app.infra.db import async_engine as ae
    from app.main import create_app

    engine = create_async_engine(async_url)
    conn = await engine.connect()
    trans = await conn.begin()
    ae._engine = engine
    ae._sessionmaker = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )

    app = create_app()
    app.state.container = build_container(mailer=fake_mailer, enqueue=enqueue_calls.append)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac
    finally:
        await trans.rollback()
        await conn.close()
        await engine.dispose()
        ae._engine = None
        ae._sessionmaker = None


@pytest_asyncio.fixture
async def committing_client(
    migrated_db: tuple[str, str, str],
    fake_mailer: FakeMailer,
    truncate_notification_tables: None,
) -> AsyncIterator[AsyncClient]:
    """Like ``client`` but COMMITS (no rollback) and uses the real Celery enqueue, so a worker
    subprocess can see the rows. Cleaned by truncation (rows outlive the request)."""
    async_url, sync_url, broker_url = migrated_db
    _reset_runtime(async_url, sync_url, broker_url)

    from httpx import ASGITransport, AsyncClient

    from app.bootstrap import build_container
    from app.infra.db.async_engine import dispose_async_engine
    from app.main import create_app

    app = create_app()
    app.state.container = build_container(mailer=fake_mailer)  # default enqueue → real broker

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac
    finally:
        await dispose_async_engine()


@pytest.fixture
def sync_session_factory(migrated_db: tuple[str, str, str]):  # type: ignore[no-untyped-def]
    """A sync sessionmaker bound to the test DB — for factories + in-process worker-path tests."""
    async_url, sync_url, broker_url = migrated_db
    _reset_runtime(async_url, sync_url, broker_url)
    from app.infra.db.sync_engine import get_sync_sessionmaker

    return get_sync_sessionmaker()


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(base_url: str, timeout: float = 30.0) -> None:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(f"{base_url}/sms/none/status", timeout=1.0)
            return  # any HTTP response (incl. 404) means the server is up
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError(f"provider_sim did not start at {base_url}")


@pytest.fixture
def provider_sim_server(migrated_db: tuple[str, str, str]) -> Iterator[str]:
    """Run the real ``app.provider_sim`` on a free port reachable by the io worker subprocess
    (deterministic success: all PROVIDER_SIM_* failure rates default to 0)."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.provider_sim.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        env={**os.environ},
    )
    try:
        _wait_http(base_url)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _wait_for_io(broker_url: str, timeout: float = 30.0) -> None:
    from celery import Celery

    probe = Celery("probe", broker=broker_url)
    deadline = time.time() + timeout
    while time.time() < deadline:
        replies = probe.control.ping(timeout=2.0) or []
        pools = {n.split("@", 1)[0] for r in replies for n in r}
        if "io" in pools:
            return
        time.sleep(0.5)
    raise RuntimeError("io worker did not become ready in time")


@pytest.fixture
def io_worker(migrated_db: tuple[str, str, str], provider_sim_server: str) -> Iterator[None]:
    """A real io-only Celery worker subprocess pointed at the in-test provider_sim, with a fast SMS
    poll cadence so confirmation tests finish quickly."""
    async_url, sync_url, broker_url = migrated_db
    env = {
        **os.environ,
        "DATABASE_URL_SYNC": sync_url,
        "BROKER_URL": broker_url,
        "PROVIDER_BASE_URL": provider_sim_server,
        # Unreachable on purpose: email/push webhook callbacks fail harmlessly (no API here).
        "WEBHOOK_CALLBACK_URL": "http://127.0.0.1:9/api/v1/webhooks/delivery",
        "SMS_POLL_INTERVAL_S": "0.3",
        "SMS_POLL_WINDOW_S": "10",
    }
    proc = _start_worker(_IO_POOL, "io@test", "io", env)
    try:
        _wait_for_io(broker_url)
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@dataclass(frozen=True)
class AuthedUser:
    user_id: UUID
    email: str
    password: str
    access_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


async def register_verify_login(
    client: AsyncClient, fake_mailer: FakeMailer, *, email: str, password: str
) -> AuthedUser:
    """Drive the real register → verify → login endpoints and return the resulting credentials."""
    from app.adapters.persistence.async_repo import AsyncAccountRepository
    from app.infra.db.async_engine import get_async_sessionmaker

    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    token = fake_mailer.verification_token_for(email)
    resp = await client.post("/api/v1/auth/verify", params={"token": token})
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    access_token = resp.json()["access_token"]

    record = await AsyncAccountRepository(get_async_sessionmaker()).get_auth_by_email(email)
    assert record is not None
    return AuthedUser(user_id=record.id, email=email, password=password, access_token=access_token)


@pytest_asyncio.fixture
async def authed_user(client: AsyncClient, fake_mailer: FakeMailer) -> AuthedUser:
    """A registered, verified, logged-in user (reused by US2/US3/US4 tests)."""
    return await register_verify_login(
        client, fake_mailer, email="ada@example.com", password="correct horse battery"
    )


@dataclass(frozen=True)
class AdminContext:
    """A rollback-isolated client plus the seeded admin's logged-in credentials (004 US1).

    ``fake_mailer`` is the same captured-token mailer bound into the app, so a test can drive
    ``register_verify_login`` to create an ordinary (non-admin) user for the 403 checks."""

    client: AsyncClient
    admin: AuthedUser
    fake_mailer: FakeMailer


@pytest_asyncio.fixture
async def admin_client(
    migrated_db: tuple[str, str, str], fake_mailer: FakeMailer
) -> AsyncIterator[AdminContext]:
    """Seed a pre-verified admin via the factory, then log in — yielding a rollback-isolated client
    bound to that admin's token. API writes (the stats-report config) roll back at teardown; the
    committed admin row is removed by truncating the 004/003 tables afterwards (T008)."""
    from tests.factories import ADMIN_TEST_PASSWORD, make_admin

    async_url, sync_url, broker_url = migrated_db
    _reset_runtime(async_url, sync_url, broker_url)

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import create_engine, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.adapters.persistence.async_repo import AsyncAccountRepository
    from app.bootstrap import build_container
    from app.infra.db import async_engine as ae
    from app.infra.db.sync_engine import get_sync_sessionmaker
    from app.main import create_app

    admin_email = "admin@example.com"
    make_admin(get_sync_sessionmaker(), email=admin_email, password=ADMIN_TEST_PASSWORD)

    engine = create_async_engine(async_url)
    conn = await engine.connect()
    trans = await conn.begin()
    ae._engine = engine
    ae._sessionmaker = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )

    app = create_app()
    app.state.container = build_container(mailer=fake_mailer, enqueue=lambda _dispatch_id: None)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.post(
                "/api/v1/auth/login",
                data={"username": admin_email, "password": ADMIN_TEST_PASSWORD},
            )
            assert resp.status_code == 200, resp.text
            access_token = resp.json()["access_token"]
            record = await AsyncAccountRepository(ae._sessionmaker).get_auth_by_email(admin_email)
            assert record is not None
            admin = AuthedUser(
                user_id=record.id,
                email=admin_email,
                password=ADMIN_TEST_PASSWORD,
                access_token=access_token,
            )
            yield AdminContext(client=ac, admin=admin, fake_mailer=fake_mailer)
    finally:
        await trans.rollback()
        await conn.close()
        await engine.dispose()
        ae._engine = None
        ae._sessionmaker = None
        cleanup = create_engine(sync_url)
        with cleanup.begin() as c:
            c.execute(
                text(f"TRUNCATE TABLE {', '.join(_NOTIFICATION_TABLES)} RESTART IDENTITY CASCADE")
            )
        cleanup.dispose()


def _start_worker(
    pool: str, nodename: str, queue: str, env: dict[str, str]
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.tasks.celery_app",
            "worker",
            f"--pool={pool}",
            "-n",
            nodename,
            "-Q",
            queue,
            "--concurrency=1",
            "--loglevel=ERROR",
            "--without-gossip",
            "--without-mingle",
            "--without-heartbeat",
        ],
        env=env,
    )


@pytest.fixture
def both_pool_workers(migrated_db: tuple[str, str, str]) -> Iterator[None]:
    """Start real workers on BOTH pools (cpu + io); readiness pings both."""
    async_url, sync_url, broker_url = migrated_db
    env = {**os.environ, "DATABASE_URL_SYNC": sync_url, "BROKER_URL": broker_url}
    procs = [
        _start_worker(_CPU_POOL, "cpu@test", "cpu", env),
        _start_worker(_IO_POOL, "io@test", "io", env),
    ]
    try:
        _wait_for_workers(broker_url)
        yield
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _wait_for_workers(broker_url: str, timeout: float = 30.0) -> None:
    from celery import Celery

    probe = Celery("probe", broker=broker_url)
    deadline = time.time() + timeout
    while time.time() < deadline:
        replies = probe.control.ping(timeout=2.0) or []
        pools = {n.split("@", 1)[0] for r in replies for n in r}
        if {"cpu", "io"} <= pools:
            return
        time.sleep(0.5)
    raise RuntimeError("workers did not become ready in time")


@dataclass
class SmtpSink:
    """A local in-process SMTP catcher reachable by a worker subprocess (004 report round-trip)."""

    host: str
    port: int
    messages: list[bytes]


@pytest.fixture
def smtp_sink() -> Iterator[SmtpSink]:
    """Run an ``aiosmtpd`` controller on a free port; capture raw message bytes (T027)."""
    from aiosmtpd.controller import Controller

    captured: list[bytes] = []

    class _Capturing:
        async def handle_DATA(self, server, session, envelope):  # noqa: N802
            captured.append(bytes(envelope.content))
            return "250 Message accepted"

    port = _free_port()
    controller = Controller(_Capturing(), hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield SmtpSink(host="127.0.0.1", port=port, messages=captured)
    finally:
        controller.stop()


def _truncate_report_tables(sync_url: str) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"TRUNCATE TABLE {', '.join(_NOTIFICATION_TABLES)}, stats_report_config "
                "RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()


@pytest.fixture
def report_workers(
    migrated_db: tuple[str, str, str], smtp_sink: SmtpSink
) -> Iterator[Callable[[], None]]:
    """Start real cpu+io workers pointed at the ``aiosmtpd`` sink and yield a ``trigger`` that fires
    ``stats_report_tick`` on the cpu queue. The test nudges the config to due, then calls trigger;
    the cpu worker runs the cycle and the io worker delivers the report emails (T027/T030).
    Committed rows (incl. the config singleton) are truncated at teardown."""
    async_url, sync_url, broker_url = migrated_db
    _reset_runtime(async_url, sync_url, broker_url)
    env = {
        **os.environ,
        "DATABASE_URL_SYNC": sync_url,
        "BROKER_URL": broker_url,
        "SMTP_HOST": smtp_sink.host,
        "SMTP_PORT": str(smtp_sink.port),
        "MAIL_FROM": "no-reply@notification.local",
        "REPORT_MAIL_FROM": "reports@notification.local",
    }
    procs = [
        _start_worker(_CPU_POOL, "cpu@test", "cpu", env),
        _start_worker(_IO_POOL, "io@test", "io", env),
    ]

    def trigger() -> None:
        from app.tasks.reporting import stats_report_tick

        stats_report_tick.apply_async(queue="cpu")

    try:
        _wait_for_workers(broker_url)
        yield trigger
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        _truncate_report_tables(sync_url)
