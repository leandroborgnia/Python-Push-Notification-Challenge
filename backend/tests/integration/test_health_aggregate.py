from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_health_200_all_healthy_with_both_pools(app, both_pool_workers):
    with TestClient(app) as client:
        start = time.perf_counter()
        response = client.get("/health")
        elapsed = time.perf_counter() - start

        body = response.json()
        assert response.status_code == 200, body
        assert body["status"] == "healthy"
        passed = {check["name"]: check["passed"] for check in body["checks"]}
        assert passed == {
            "data_store": True,
            "message_broker": True,
            "worker_pool_cpu": True,
            "worker_pool_io": True,
        }

        # Probes stay 2xx alongside a healthy aggregate.
        assert client.get("/livez").status_code == 200
        assert client.get("/readyz").status_code == 200

    # SC-005: normal-case target is < 1s; assert a generous, non-flaky upper bound here.
    assert elapsed < 3.0


def test_health_503_when_workers_down_probes_stay_2xx(app):
    # DB + broker up (containers), but no workers running → aggregate 503, probes unaffected.
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 503
        passed = {check["name"]: check["passed"] for check in response.json()["checks"]}
        assert passed["data_store"] is True
        assert passed["worker_pool_cpu"] is False
        assert passed["worker_pool_io"] is False

        # FR-014 / SC-010: liveness & readiness must NOT be gated on workers.
        assert client.get("/livez").status_code == 200
        assert client.get("/readyz").status_code == 200
