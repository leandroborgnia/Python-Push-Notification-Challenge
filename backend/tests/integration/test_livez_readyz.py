from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_container
from app.application.liveness import ReadinessService
from app.bootstrap import build_container
from app.domain.health import SubsystemCheck, SubsystemName

pytestmark = pytest.mark.integration


class FailingDataStore:
    async def check(self) -> SubsystemCheck:
        return SubsystemCheck(SubsystemName.DATA_STORE, passed=False, detail="down")


def test_livez_always_200_and_readyz_200_when_db_up(app):
    with TestClient(app) as client:
        live = client.get("/livez")
        assert live.status_code == 200
        assert live.json()["status"] == "alive"

        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"


def test_readyz_503_when_db_unreachable_but_livez_stays_200(app):
    base = build_container()
    failing = dataclasses.replace(base, readiness=ReadinessService(FailingDataStore()))
    app.dependency_overrides[get_container] = lambda: failing
    try:
        with TestClient(app) as client:
            assert client.get("/livez").status_code == 200  # liveness never gated on DB
            ready = client.get("/readyz")
            assert ready.status_code == 503
            assert ready.json()["status"] == "not_ready"
    finally:
        app.dependency_overrides.clear()
