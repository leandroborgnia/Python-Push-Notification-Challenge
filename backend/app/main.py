from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from app.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_telemetry()
    app.state.container = build_container()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Notification Service", lifespan=lifespan)
    # Cross-origin enablement so the browser SPA at app.localhost can call the API at api.localhost.
    # Bearer-header auth (no cookies) ⇒ allow_credentials=False, which keeps the explicit origin
    # allow-list valid (a "*" origin with credentials is forbidden). Feature 005, FR-040.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_allow_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
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
