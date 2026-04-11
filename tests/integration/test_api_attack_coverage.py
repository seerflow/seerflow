"""End-to-end integration + performance test for /api/v1/attack/coverage."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.sigma.attack import TACTICS
from seerflow.sigma.engine import SigmaEngine
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def backend(tmp_path: Path) -> SqliteBackend:
    db_path = str(tmp_path / "test_attack_coverage.db")
    config = StorageConfig(backend="sqlite", sqlite_path=db_path)
    b = await SqliteBackend.connect(config)
    yield b  # type: ignore[misc]
    await b.close()


def _make_alert(i: int) -> Alert:
    return Alert(
        alert_id=f"perf-a{i}",
        alert_type="sigma",
        timestamp_ns=1_775_736_000_000_000_000 + i,
        severity_id=SeverityLevel.WARNING,
        rule_name="test",
        description="",
        entity_uuid="e",
        entity_value="1.2.3.4",
        entity_type="ip",
        contributing_events=(),
        mitre_tactics=("discovery",),
        mitre_techniques=("t1033",),
        dedup_key=f"perf:{i}",
    )


class TestAttackCoverageIntegration:
    async def test_returns_known_tactics_with_empty_engine(
        self, backend: SqliteBackend
    ) -> None:
        app = create_api_app(log_store=backend, alert_store=backend)
        client = TestClient(app)
        response = client.get("/api/v1/attack/coverage")
        assert response.status_code == 200
        body = response.json()
        assert [t["tactic"] for t in body["tactics"]] == list(TACTICS.keys())

    async def test_reflects_bundled_sigma_rules(self, backend: SqliteBackend) -> None:
        engine = SigmaEngine()
        engine.load_bundled()
        app = create_api_app(
            log_store=backend,
            alert_store=backend,
            sigma_engine=engine,
        )
        client = TestClient(app)
        response = client.get("/api/v1/attack/coverage")
        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["total_rules_with_attack_tags"] > 0
        covered_any = any(
            cell["covered"]
            for tactic in body["tactics"]
            for cell in tactic["techniques"]
        )
        assert covered_any

    async def test_perf_under_500ms_with_10k_alerts(
        self, backend: SqliteBackend
    ) -> None:
        for i in range(10_000):
            await backend.write_alert(_make_alert(i), dedup_window_ns=0)
        app = create_api_app(log_store=backend, alert_store=backend)
        client = TestClient(app)
        # Warm-up request — primes msgpack/Pydantic codepaths.
        client.get("/api/v1/attack/coverage")
        t0 = time.perf_counter()
        response = client.get("/api/v1/attack/coverage")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert response.status_code == 200
        assert elapsed_ms < 500, f"coverage took {elapsed_ms:.1f}ms"
        body = response.json()
        discovery = next(t for t in body["tactics"] if t["tactic"] == "discovery")
        assert discovery["techniques"][0]["alert_count"] == 10_000
