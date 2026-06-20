from __future__ import annotations

import asyncio
import sys

from app.adapters.persistence.async_repo import AsyncLivenessCompletionReader
from app.application.smoke import SmokeCheckService
from app.infra.db.async_engine import dispose_async_engine, get_async_sessionmaker
from app.infra.telemetry import init_telemetry
from app.settings import get_settings


async def _run() -> int:
    settings = get_settings()
    reader = AsyncLivenessCompletionReader(get_async_sessionmaker())
    service = SmokeCheckService(reader, settings.smoke_timeout_s)
    try:
        result = await service.run()
    finally:
        await dispose_async_engine()

    if result.ok:
        print(f"smoke-check: ok (correlation_id={result.correlation_id})")
        return 0
    print(
        f"smoke-check: FAILED (correlation_id={result.correlation_id}); "
        f"missing pools: {sorted(result.missing_pools)}",
        file=sys.stderr,
    )
    return 1


def main() -> None:
    init_telemetry()
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
