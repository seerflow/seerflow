"""Integration tests for /api/v1/sigma/rules endpoints (S-151)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import DetectionConfig, SeerflowConfig
from seerflow.sigma.engine import SigmaEngine

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

    from seerflow.storage.sqlite import SqliteBackend


_RULE_YAML = """
title: Sigma S151 Routes Test Rule
logsource:
  product: linux
  category: process_creation
detection:
  sel:
    message|contains: 's151-route-token'
  condition: sel
"""

_NEW_UPLOAD_YAML = """
title: Sigma S151 Uploaded Route Rule
logsource:
  product: linux
  category: process_creation
detection:
  sel:
    message|contains: 's151-uploaded-token'
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
):
    cfg = SeerflowConfig(detection=DetectionConfig(sigma_custom_upload_dir=str(upload_dir)))
    return create_api_app(
        log_store=backend,
        alert_store=backend,
        config=cfg,
        sigma_engine=engine_with_one_rule,
        sigma_state_store=backend,
    )


def test_list_returns_loaded_rules(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        resp = client.get("/api/v1/sigma/rules")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert "items" in body


def test_get_single_returns_yaml_source(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        rid = client.get("/api/v1/sigma/rules").json()["items"][0]["rule_id"]
        resp = client.get(f"/api/v1/sigma/rules/{rid}")
        assert resp.status_code == 200
        body = resp.json()
        assert "yaml_source" in body
        assert body["rule_id"] == rid


def test_get_unknown_returns_404(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        resp = client.get("/api/v1/sigma/rules/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


def test_filter_by_search_substring(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        resp = client.get("/api/v1/sigma/rules?search=routes-test")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all("routes" in i["title"].lower() for i in items)


def test_pagination(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        resp = client.get("/api/v1/sigma/rules?page=1&limit=1")
        body = resp.json()
        assert body["page"] == 1
        assert body["limit"] == 1
        assert len(body["items"]) <= 1


def test_patch_toggles_enabled_and_persists(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        rid = client.get("/api/v1/sigma/rules").json()["items"][0]["rule_id"]
        resp = client.patch(f"/api/v1/sigma/rules/{rid}", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
        # Re-fetch confirms persistence
        again = client.get(f"/api/v1/sigma/rules/{rid}").json()
        assert again["enabled"] is False


def test_patch_unknown_rule_returns_404(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        resp = client.patch(
            "/api/v1/sigma/rules/00000000-0000-0000-0000-000000000000",
            json={"enabled": False},
        )
        assert resp.status_code == 404


def test_dry_run_validate_valid(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        resp = client.post("/api/v1/sigma/rules?dry_run=true", json={"yaml": _NEW_UPLOAD_YAML})
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["rule_id"]


def test_dry_run_invalid_returns_stage(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        resp = client.post("/api/v1/sigma/rules?dry_run=true", json={"yaml": "title: x\n  bad: ["})
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["stage"] == "yaml"
        assert body["line"] is not None


def test_post_persists_and_indexes(app_with_sigma, upload_dir: Path) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        resp = client.post("/api/v1/sigma/rules", json={"yaml": _NEW_UPLOAD_YAML})
        assert resp.status_code == 201
        body = resp.json()
        rid = body["rule_id"]
        assert (upload_dir / f"{rid}.yml").exists()
        listed = client.get("/api/v1/sigma/rules").json()["items"]
        assert any(r["rule_id"] == rid for r in listed)


def test_post_collision_returns_409(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        resp1 = client.post("/api/v1/sigma/rules", json={"yaml": _NEW_UPLOAD_YAML})
        assert resp1.status_code == 201
        resp2 = client.post("/api/v1/sigma/rules", json={"yaml": _NEW_UPLOAD_YAML})
        assert resp2.status_code == 409
        assert resp2.json()["collision"] is True


def test_post_invalid_yaml_returns_422(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_with_sigma) as client:
        resp = client.post("/api/v1/sigma/rules", json={"yaml": "not yaml: ["})
        assert resp.status_code == 422


def test_post_no_upload_dir_returns_422(backend: SqliteBackend) -> None:
    cfg = SeerflowConfig(detection=DetectionConfig(sigma_custom_upload_dir=None))
    engine = SigmaEngine()
    app = create_api_app(log_store=backend, alert_store=backend, config=cfg, sigma_engine=engine)
    with TestClient(app) as client:
        resp = client.post("/api/v1/sigma/rules", json={"yaml": _NEW_UPLOAD_YAML})
        assert resp.status_code == 422


def test_no_engine_returns_503(backend: SqliteBackend) -> None:
    app = create_api_app(log_store=backend, alert_store=backend, sigma_engine=None)
    with TestClient(app) as client:
        resp = client.get("/api/v1/sigma/rules")
        assert resp.status_code == 503


def test_alert_count_24h_populated_when_alerts_exist(
    app_with_sigma,  # type: ignore[no-untyped-def]
    backend: SqliteBackend,
    engine_with_one_rule: SigmaEngine,
) -> None:
    """S-151 review: ``alert_count_24h`` must be > 0 after firing the rule.

    Catches the title↔rule_name key mismatch raised by code review: if
    ``Alert.rule_name`` and ``rule['title']`` ever drift, the count silently
    returns 0. Round-trip through real ``evaluate`` + AlertStore.
    """
    import asyncio

    from tests.helpers import make_event

    event = make_event(
        message="contains s151-route-token here",
        log_source_product="linux",
        log_source_category="process_creation",
    )
    alerts = engine_with_one_rule.evaluate(event)
    assert len(alerts) == 1, "rule should match the test event"
    asyncio.run(backend.write_alert(alerts[0]))

    with TestClient(app_with_sigma) as client:
        body = client.get("/api/v1/sigma/rules").json()
        target = body["items"][0]
        assert target["alert_count_24h"] == 1, (
            f"alert_count_24h should reflect persisted alerts; got {target}"
        )


def test_yaml_anchor_bomb_rejected(app_with_sigma) -> None:  # type: ignore[no-untyped-def]
    """Hostile payload with >32 anchors fails fast in the validator."""
    payload = "title: T\n" + "\n".join(f"k{i}: &a{i} x" for i in range(40))
    with TestClient(app_with_sigma) as client:
        resp = client.post("/api/v1/sigma/rules?dry_run=true", json={"yaml": payload})
        body = resp.json()
        assert body["valid"] is False
        assert body["stage"] == "yaml"
        assert "anchors" in body["message"]


def test_disabled_state_persists_across_app_restart(
    backend: SqliteBackend,
    upload_dir: Path,
    tmp_path: Path,
) -> None:
    """S-151: state survives engine rebuild via attach_state_store hydration."""
    cfg = SeerflowConfig(detection=DetectionConfig(sigma_custom_upload_dir=str(upload_dir)))
    e1 = SigmaEngine()
    rule_path = tmp_path / "fixture.yml"
    rule_path.write_text(_RULE_YAML)
    e1.load_rules([rule_path])
    app1 = create_api_app(
        log_store=backend,
        alert_store=backend,
        config=cfg,
        sigma_engine=e1,
        sigma_state_store=backend,
    )
    with TestClient(app1) as c1:
        rid = c1.get("/api/v1/sigma/rules").json()["items"][0]["rule_id"]
        c1.patch(f"/api/v1/sigma/rules/{rid}", json={"enabled": False})

    e2 = SigmaEngine()
    e2.load_rules([rule_path])
    app2 = create_api_app(
        log_store=backend,
        alert_store=backend,
        config=cfg,
        sigma_engine=e2,
        sigma_state_store=backend,
    )
    with TestClient(app2) as c2:
        listed = c2.get("/api/v1/sigma/rules").json()["items"]
        target = next(r for r in listed if r["rule_id"] == rid)
        assert target["enabled"] is False


_MULTI_SEVERITY_RULES = [
    (
        "high",
        """
title: Sigma S154 High Severity Rule
logsource:
  product: linux
  category: process_creation
detection:
  sel:
    message|contains: 's154-high-token'
  condition: sel
level: high
""",
    ),
    (
        "critical",
        """
title: Sigma S154 Critical Severity Rule
logsource:
  product: linux
  category: process_creation
detection:
  sel:
    message|contains: 's154-critical-token'
  condition: sel
level: critical
""",
    ),
    (
        "medium",
        """
title: Sigma S154 Medium Severity Rule
logsource:
  product: linux
  category: process_creation
detection:
  sel:
    message|contains: 's154-medium-token'
  condition: sel
level: medium
""",
    ),
]


@pytest.fixture
def app_with_multi_severity(
    backend: SqliteBackend,
    upload_dir: Path,
    tmp_path: Path,
) -> FastAPI:
    """App fixture seeded with rules at severity 3 (medium), 4 (high), 5 (critical)."""
    cfg = SeerflowConfig(detection=DetectionConfig(sigma_custom_upload_dir=str(upload_dir)))
    engine = SigmaEngine()
    paths = []
    for slug, yaml_text in _MULTI_SEVERITY_RULES:
        p = tmp_path / f"sev-{slug}.yml"
        p.write_text(yaml_text)
        paths.append(p)
    engine.load_rules(paths)
    return create_api_app(
        log_store=backend,
        alert_store=backend,
        config=cfg,
        sigma_engine=engine,
        sigma_state_store=backend,
    )


def test_list_rules_severity_in_multiple(app_with_multi_severity: FastAPI) -> None:
    """severity_in repeated query param accepts multiple severities."""
    with TestClient(app_with_multi_severity) as client:
        resp = client.get("/api/v1/sigma/rules?severity_in=4&severity_in=5&limit=200")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items, "fixture must seed at least one severity 4 or 5 rule"
        assert all(it["severity"] in (4, 5) for it in items)


def test_list_rules_severity_in_empty_is_no_filter(app_with_multi_severity: FastAPI) -> None:
    with TestClient(app_with_multi_severity) as client:
        resp = client.get("/api/v1/sigma/rules?limit=500")
        baseline = resp.json()["total"]
        resp2 = client.get("/api/v1/sigma/rules?severity_in=&limit=500")
        assert resp2.status_code == 200
        assert resp2.json()["total"] == baseline


def test_list_rules_severity_param_removed(app_with_multi_severity: FastAPI) -> None:
    """Single ?severity= must no longer narrow the list (param dropped)."""
    with TestClient(app_with_multi_severity) as client:
        resp_with = client.get("/api/v1/sigma/rules?severity=3&limit=500")
        resp_without = client.get("/api/v1/sigma/rules?limit=500")
        assert resp_with.json()["total"] == resp_without.json()["total"]


def test_list_rules_severity_in_rejects_non_integer(app_with_multi_severity: FastAPI) -> None:
    """Non-integer ``severity_in`` token must surface as 422, not silent drop."""
    with TestClient(app_with_multi_severity) as client:
        resp = client.get("/api/v1/sigma/rules?severity_in=foo")
        assert resp.status_code == 422


def test_list_rules_severity_in_rejects_out_of_range(app_with_multi_severity: FastAPI) -> None:
    """Severity outside the OTel [0, 24] band must surface as 422."""
    with TestClient(app_with_multi_severity) as client:
        resp = client.get("/api/v1/sigma/rules?severity_in=99")
        assert resp.status_code == 422


def test_list_rules_severity_in_rejects_too_many_values(app_with_multi_severity: FastAPI) -> None:
    """severity_in with > _MAX_SEVERITY_IN repetitions must short-circuit to 422."""
    qs = "&".join(f"severity_in={i % 25}" for i in range(30))
    with TestClient(app_with_multi_severity) as client:
        resp = client.get(f"/api/v1/sigma/rules?{qs}")
        assert resp.status_code == 422


def test_list_rules_response_envelope_has_has_next(app_with_multi_severity: FastAPI) -> None:
    """List envelope must expose has_next so pagination matches PaginatedResponse[T]."""
    with TestClient(app_with_multi_severity) as client:
        resp = client.get("/api/v1/sigma/rules?page=1&limit=2")
        body = resp.json()
        assert {"items", "total", "page", "limit", "has_next"} <= set(body.keys())
        assert isinstance(body["has_next"], bool)


def test_list_rules_has_next_true_on_first_page(app_with_multi_severity: FastAPI) -> None:
    """has_next must be True when total > page*limit (first page, fixture has 3 rules)."""
    with TestClient(app_with_multi_severity) as client:
        resp = client.get("/api/v1/sigma/rules?page=1&limit=1")
        body = resp.json()
        assert body["total"] >= 2  # sanity: fixture seeded enough rules
        assert body["has_next"] is True


def test_list_rules_has_next_false_on_last_page(app_with_multi_severity: FastAPI) -> None:
    """has_next must be False when requesting a page past the last."""
    with TestClient(app_with_multi_severity) as client:
        resp = client.get("/api/v1/sigma/rules?page=999&limit=10")
        body = resp.json()
        assert body["has_next"] is False
