from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi import FastAPI

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
