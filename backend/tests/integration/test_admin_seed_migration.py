from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import _POSTGRES_IMAGE

pytestmark = pytest.mark.integration

_ADMIN_EMAIL = "seed-admin@example.com"
_ADMIN_PASSWORD = "seed-admin-secret-pw"

_SEED_SQL = text(
    "INSERT INTO user_account (email, password_hash, is_verified, is_admin) "
    "VALUES (lower(:email), :password_hash, true, true) "
    "ON CONFLICT (lower(email)) DO NOTHING"
)


@pytest.fixture
def clean_db_with_admin_env() -> Iterator[str]:
    """A dedicated, empty Postgres + env so the real Alembic migration (incl. the admin data seed)
    runs end to end (T012/G1). Restores env + engine/settings caches on teardown."""
    from testcontainers.postgres import PostgresContainer

    saved = {
        key: os.environ.get(key)
        for key in (
            "DATABASE_URL_SYNC",
            "DATABASE_URL_ASYNC",
            "ADMIN_EMAIL",
            "ADMIN_PASSWORD",
            "ENVIRONMENT",
        )
    }
    with PostgresContainer(_POSTGRES_IMAGE) as pg:
        base = pg.get_connection_url()  # postgresql+psycopg2://...
        sync_url = base.replace("+psycopg2", "+psycopg")
        os.environ["DATABASE_URL_SYNC"] = sync_url
        os.environ["DATABASE_URL_ASYNC"] = base.replace("+psycopg2", "+asyncpg")
        os.environ["ADMIN_EMAIL"] = _ADMIN_EMAIL
        os.environ["ADMIN_PASSWORD"] = _ADMIN_PASSWORD
        os.environ["ENVIRONMENT"] = "dev"
        _reset_engine_and_settings()
        try:
            yield sync_url
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            _reset_engine_and_settings()


def _reset_engine_and_settings() -> None:
    from app.infra.db import sync_engine
    from app.settings import get_settings

    get_settings.cache_clear()
    sync_engine._engine = None
    sync_engine._sessionmaker = None


def _alembic_upgrade_head() -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    command.upgrade(cfg, "head")


def _admin_rows(sync_url: str) -> list[tuple[str, bool, bool]]:
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT password_hash, is_verified, is_admin FROM user_account "
                    "WHERE lower(email) = lower(:email)"
                ),
                {"email": _ADMIN_EMAIL},
            )
            return [(row[0], row[1], row[2]) for row in result]
    finally:
        engine.dispose()


def test_migration_seeds_exactly_one_verified_admin(clean_db_with_admin_env: str) -> None:
    from app.adapters.security.hasher import Argon2PasswordHasher

    _alembic_upgrade_head()

    rows = _admin_rows(clean_db_with_admin_env)
    assert len(rows) == 1
    password_hash, is_verified, is_admin = rows[0]
    assert is_verified is True
    assert is_admin is True
    assert Argon2PasswordHasher().verify(_ADMIN_PASSWORD, password_hash) is True


def test_reseeding_is_idempotent(clean_db_with_admin_env: str) -> None:
    _alembic_upgrade_head()

    # Re-provisioning (same email, even a different hash) must not duplicate or overwrite (FR-001).
    engine = create_engine(clean_db_with_admin_env)
    try:
        with engine.begin() as conn:
            conn.execute(
                _SEED_SQL, {"email": _ADMIN_EMAIL, "password_hash": "a-different-hash-value"}
            )
    finally:
        engine.dispose()

    rows = _admin_rows(clean_db_with_admin_env)
    assert len(rows) == 1
    assert rows[0][0] != "a-different-hash-value"  # original hash preserved (DO NOTHING)
