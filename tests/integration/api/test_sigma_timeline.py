"""Integration tests for GET /api/v1/sigma/rules/{rule_id}/timeline (S-154 Task 2)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.api.routes.sigma import _HOUR_NS as HOUR_NS
from seerflow.config import DetectionConfig, SeerflowConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.sigma.engine import SigmaEngine
from tests.conftest import FrozenDatetime

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

    from seerflow.storage.sqlite import SqliteBackend


_RULE_YAML = """
title: Sigma S154 Timeline Rule
logsource:
  product: linux
  category: process_creation
detection:
  sel:
    message|contains: 's154-timeline-token'
  condition: sel
"""


@pytest.fixture
def engine_with_one_rule(tmp_path: Path) -> SigmaEngine:
    e = SigmaEngine()
    rule_path = tmp_path / "fixture.yml"
    rule_path.write_text(_RULE_YAML)
    e.load_rules([rule_path])
    return e


@pytest.fixture
def upload_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sigma-uploads"
    d.mkdir()
    return d


@pytest.fixture
def app_with_sigma(
    backend: SqliteBackend,
    engine_with_one_rule: SigmaEngine,
    upload_dir: Path,
) -> FastAPI:
    cfg = SeerflowConfig(detection=DetectionConfig(sigma_custom_upload_dir=str(upload_dir)))
    return create_api_app(
        log_store=backend,
        alert_store=backend,
        config=cfg,
        sigma_engine=engine_with_one_rule,
        sigma_state_store=backend,
    )


def _alert(ts_ns: int, *, rule_name: str) -> Alert:
    """Build a minimal Sigma Alert at ``ts_ns`` for ``rule_name``."""
    return Alert(
        alert_id=f"a-{ts_ns}-{rule_name}",
        alert_type="sigma",
        timestamp_ns=ts_ns,
        severity_id=SeverityLevel.WARNING,
        rule_name=rule_name,
        description="t",
        entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, "host:web-01")),
        entity_value="web-01",
        entity_type="host",
        contributing_events=(uuid.uuid4(),),
        dedup_key=f"dk-{ts_ns}-{rule_name}",
    )


def test_timeline_returns_24_buckets_with_zero_fill(
    app_with_sigma: FastAPI,
    backend: SqliteBackend,
    engine_with_one_rule: SigmaEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 alerts → bucket[0]=2, bucket[1]=1, rest 0; 24 buckets total."""
    import asyncio

    rid = engine_with_one_rule.list_rules()[0]["rule_id"]
    rule_title = str(engine_with_one_rule.list_rules()[0]["title"])

    # Pick an aligned base hour. The window is half-open [now-24h, now);
    # set ``now = base + 24h`` so ``start_ns = base`` and the dense grid is
    # exactly [base, base+HOUR, ..., base+23*HOUR]. The latest seeded alert
    # is base+HOUR+5, well inside the window.
    base = 1_761_350_400_000_000_000  # arbitrary HOUR-aligned ns
    now_ns = base + 24 * HOUR_NS

    asyncio.run(backend.write_alert(_alert(base, rule_name=rule_title)))
    asyncio.run(backend.write_alert(_alert(base + 1, rule_name=rule_title)))
    asyncio.run(backend.write_alert(_alert(base + HOUR_NS + 5, rule_name=rule_title)))

    monkeypatch.setattr(
        "seerflow.api.routes.sigma.datetime",
        FrozenDatetime(now_ns),
    )

    with TestClient(app_with_sigma) as client:
        resp = client.get(f"/api/v1/sigma/rules/{rid}/timeline")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        buckets = body["buckets"]
        assert len(buckets) == 24
        # Ascending order.
        starts = [b["bucket_start_ns"] for b in buckets]
        assert starts == sorted(starts)
        # First bucket holds the two alerts at base/base+1; second bucket
        # holds the alert at base+HOUR+5; everything else is zero-filled.
        assert buckets[0]["count"] == 2
        assert buckets[1]["count"] == 1
        assert sum(b["count"] for b in buckets[2:]) == 0


def test_timeline_unknown_rule_id_404(
    app_with_sigma: FastAPI,
) -> None:
    with TestClient(app_with_sigma) as client:
        resp = client.get("/api/v1/sigma/rules/does-not-exist/timeline")
        assert resp.status_code == 404


def test_timeline_empty_returns_24_zero_buckets(
    app_with_sigma: FastAPI,
    engine_with_one_rule: SigmaEngine,
) -> None:
    rid = engine_with_one_rule.list_rules()[0]["rule_id"]
    with TestClient(app_with_sigma) as client:
        resp = client.get(f"/api/v1/sigma/rules/{rid}/timeline")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["buckets"]) == 24
        assert all(b["count"] == 0 for b in body["buckets"])


def test_timeline_bucket_start_ns_serialized_as_string(
    app_with_sigma: FastAPI,
    engine_with_one_rule: SigmaEngine,
) -> None:
    """JSON wire value must be a string for FE bigint revival (S-199 pattern).

    The frontend BIGINT_KEYS walker only revives ``bucket_start_ns`` to a
    JS bigint when the wire value is a JSON string; a raw JSON number would
    be left as a JS ``number`` and crash the valibot ``v.bigint()`` check
    silently dropping the sparkline. Asserting the exact wire shape here
    locks in the contract.
    """
    rid = engine_with_one_rule.list_rules()[0]["rule_id"]
    with TestClient(app_with_sigma) as client:
        resp = client.get(f"/api/v1/sigma/rules/{rid}/timeline")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for b in body["buckets"]:
            assert isinstance(b["bucket_start_ns"], str), (
                f"bucket_start_ns must be JSON string, got {type(b['bucket_start_ns']).__name__}"
            )
            assert b["bucket_start_ns"].isdigit(), (
                f"bucket_start_ns must be digits-only string, got {b['bucket_start_ns']!r}"
            )
