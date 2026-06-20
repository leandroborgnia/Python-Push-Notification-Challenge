from __future__ import annotations

import pytest

from app.adapters.persistence.async_repo import AsyncLivenessCompletionReader
from app.application.smoke import SmokeCheckService
from app.infra.db.async_engine import get_async_sessionmaker

pytestmark = pytest.mark.integration


async def test_smoke_round_trips_both_pools(migrated_db, both_pool_workers, truncate_completions):
    # Real task → real broker → real worker (per pool) → sync-write → async-read (FR-009).
    reader = AsyncLivenessCompletionReader(get_async_sessionmaker())
    service = SmokeCheckService(reader, timeout=25.0)

    result = await service.run()

    assert result.ok is True
    assert result.completed_pools == {"cpu", "io"}
    assert result.missing_pools == set()
