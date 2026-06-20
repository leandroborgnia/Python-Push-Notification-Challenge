from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers.health import router as health_router
from app.bootstrap import build_container
from app.infra.telemetry import init_telemetry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_telemetry()
    app.state.container = build_container()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Notification Service — System Liveness", lifespan=lifespan)
    app.include_router(health_router)
    return app


app = create_app()
