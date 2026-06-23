from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import install_exception_handlers
from app.api.routers.admin import router as admin_router
from app.api.routers.auth import router as auth_router
from app.api.routers.contacts import router as contacts_router
from app.api.routers.health import router as health_router
from app.api.routers.sends import router as sends_router
from app.api.routers.templates import router as templates_router
from app.api.routers.webhooks import router as webhooks_router
from app.bootstrap import build_container
from app.infra.telemetry import init_telemetry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_telemetry()
    app.state.container = build_container()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Notification Service", lifespan=lifespan)
    install_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(contacts_router)
    app.include_router(templates_router)
    app.include_router(sends_router)
    app.include_router(webhooks_router)
    app.include_router(admin_router)
    return app


app = create_app()
