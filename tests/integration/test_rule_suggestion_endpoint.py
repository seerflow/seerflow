"""Integration tests for the Sigma rule-suggestion endpoints (S-100, FR-066).

Drives the full FastAPI app through ``TestClient`` with a real
``SqliteBackend`` and a monkeypatched LLM backend. Verifies the full TP
→ aggregate → suggest → invalidate flow and the disabled-LLM 503 branches.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import LLMConfig
from seerflow.llm.rule_suggestion.cache import RuleSuggestionCache
from seerflow.llm.rule_suggestion.service import RuleSuggestionService
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


_VALID_YAML = """\
title: SSH brute force from external IP
id: 5e3b14a2-9e9d-4a5b-94f4-c2c5d3e4f1aa
status: experimental
description: Detects repeated failed SSH logins from a single source IP.
author: Seerflow LLM (drafted from TP feedback)
date: 2026-05-13
logsource:
    category: authentication
    product: linux
detection:
    selection:
        action: ssh_failed
    condition: selection
falsepositives:
    - Automated security scans
level: medium
"""


class FakeBackend:
    """Synchronous-equivalent fake matching ``LLMBackend`` Protocol."""

    name = "fake-backend"

    def __init__(self, response: str | None = None) -> None:
        self.response = response if response is not None else _VALID_YAML
        self.call_count = 0

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: tuple[str, ...] = (),
    ) -> str:
        self.call_count += 1
        return f"```yaml\n{self.response}\n```"


def _alert(alert_id: str) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type="ml",
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name="hst-anomaly",
        description="anomaly",
        entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, alert_id)),
        entity_value=f"10.0.0.{alert_id[-1]}",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        dedup_key=f"hst:1:syslog:{alert_id}",
    )


def _event() -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        source_type="syslog",
        message="ssh: invalid user from 10.0.0.1",
        template_id=42,
    )


@pytest.fixture
async def seeded_storage(backend: SqliteBackend) -> SqliteBackend:
    """SqliteBackend with 3 TP-confirmed alerts for ``ml:hst-anomaly:ip``."""
    for i in range(3):
        alert_id = f"a-{i}"
        alert = _alert(alert_id)
        await backend.write_events([_event()])
        await backend.flush()
        await backend.write_alert(alert)
        await backend.append_feedback_event(
            alert_id=alert_id,
            feedback="tp",
            note="",
            origin="dashboard",
            submitted_at_ns=1_700_000_000_000_000_000 + i,
        )
    return backend


@pytest.fixture
def rule_suggestion_client(seeded_storage: SqliteBackend) -> TestClient:
    fake = FakeBackend()
    cache = RuleSuggestionCache(max_entries=4, ttl_seconds=60)
    service = RuleSuggestionService(
        backend=fake,  # type: ignore[arg-type]
        cache=cache,
        cfg=LLMConfig(),
        alert_store=seeded_storage,
        log_store=seeded_storage,
    )
    app = create_api_app(
        log_store=seeded_storage,
        alert_store=seeded_storage,
        rule_suggestion_service=service,
        health_state={"pipeline": "running", "storage": "connected", "llm": "ready"},
    )
    client = TestClient(app)
    # Surface the backend on the client so tests can inspect call_count.
    client.app.state._test_backend = fake  # type: ignore[attr-defined]
    return client


@pytest.fixture
def no_llm_client(backend: SqliteBackend) -> TestClient:
    app = create_api_app(
        log_store=backend,
        alert_store=backend,
        rule_suggestion_service=None,
        health_state={"pipeline": "running", "storage": "connected", "llm": "disabled"},
    )
    return TestClient(app)


# ---- AC6 GET /sigma/rule-suggestions -------------------------------------


def test_list_503_when_service_none(no_llm_client: TestClient) -> None:
    resp = no_llm_client.get("/api/v1/sigma/rule-suggestions")
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["detail"] == "llm_not_ready"
    assert body["detail"]["status"] == "disabled"


def test_list_returns_eligible_patterns(rule_suggestion_client: TestClient) -> None:
    resp = rule_suggestion_client.get("/api/v1/sigma/rule-suggestions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    pattern = body["items"][0]
    assert pattern["pattern_key"] == "ml:hst-anomaly:ip"
    assert pattern["tp_count"] == 3
    assert len(pattern["contributing_alert_ids"]) == 3


def test_list_empty_when_no_eligible_patterns(backend: SqliteBackend) -> None:
    fake = FakeBackend()
    service = RuleSuggestionService(
        backend=fake,  # type: ignore[arg-type]
        cache=RuleSuggestionCache(max_entries=4, ttl_seconds=60),
        cfg=LLMConfig(),
        alert_store=backend,
        log_store=backend,
    )
    app = create_api_app(
        log_store=backend,
        alert_store=backend,
        rule_suggestion_service=service,
        health_state={"pipeline": "running", "storage": "connected", "llm": "ready"},
    )
    client = TestClient(app)
    resp = client.get("/api/v1/sigma/rule-suggestions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


# ---- AC7 POST /sigma/rule-suggestions/{pattern_key} ---------------------


def test_post_503_when_service_none(no_llm_client: TestClient) -> None:
    resp = no_llm_client.post("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    assert resp.status_code == 503


def test_post_422_invalid_pattern_key(rule_suggestion_client: TestClient) -> None:
    # Uppercase + spaces violate the regex.
    resp = rule_suggestion_client.post("/api/v1/sigma/rule-suggestions/INVALID%20KEY")
    assert resp.status_code == 422


def test_post_404_when_pattern_not_eligible(rule_suggestion_client: TestClient) -> None:
    resp = rule_suggestion_client.post("/api/v1/sigma/rule-suggestions/ml:other:ip")
    assert resp.status_code == 404
    assert resp.json()["detail"]["detail"] == "pattern_not_eligible"


def test_post_200_returns_drafted_yaml(rule_suggestion_client: TestClient) -> None:
    resp = rule_suggestion_client.post("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pattern_key"] == "ml:hst-anomaly:ip"
    assert body["tp_count"] == 3
    assert "title: SSH brute force" in body["yaml"]
    assert body["validation_stage"] == "ok"
    assert body["title"] == "SSH brute force from external IP"
    assert body["cached"] is False


def test_post_caches_subsequent_calls(rule_suggestion_client: TestClient) -> None:
    fake = rule_suggestion_client.app.state._test_backend  # type: ignore[attr-defined]
    rule_suggestion_client.post("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    assert fake.call_count == 1
    second = rule_suggestion_client.post("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert fake.call_count == 1  # no second backend call


def test_post_502_when_backend_raises(seeded_storage: SqliteBackend) -> None:
    class BoomBackend:
        name = "boom"

        async def complete(
            self,
            prompt: str,
            *,
            max_tokens: int = 256,
            temperature: float = 0.2,
            stop: tuple[str, ...] = (),
        ) -> str:
            raise RuntimeError("oops")

    service = RuleSuggestionService(
        backend=BoomBackend(),  # type: ignore[arg-type]
        cache=RuleSuggestionCache(max_entries=4, ttl_seconds=60),
        cfg=LLMConfig(),
        alert_store=seeded_storage,
        log_store=seeded_storage,
    )
    app = create_api_app(
        log_store=seeded_storage,
        alert_store=seeded_storage,
        rule_suggestion_service=service,
        health_state={"pipeline": "running", "storage": "connected", "llm": "ready"},
    )
    client = TestClient(app)
    resp = client.post("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    assert resp.status_code == 502
    assert resp.json()["detail"]["detail"] == "llm_failed"


# ---- AC8 DELETE /sigma/rule-suggestions/{pattern_key} -------------------


def test_delete_503_when_service_none(no_llm_client: TestClient) -> None:
    resp = no_llm_client.delete("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    assert resp.status_code == 503


def test_delete_422_invalid_pattern_key(rule_suggestion_client: TestClient) -> None:
    resp = rule_suggestion_client.delete("/api/v1/sigma/rule-suggestions/INVALID%20KEY")
    assert resp.status_code == 422


def test_delete_204_idempotent(rule_suggestion_client: TestClient) -> None:
    # Delete a never-cached entry — still 204.
    resp = rule_suggestion_client.delete("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    assert resp.status_code == 204
    # Idempotent: second call also 204.
    resp = rule_suggestion_client.delete("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    assert resp.status_code == 204


def test_delete_invalidates_cache(rule_suggestion_client: TestClient) -> None:
    fake = rule_suggestion_client.app.state._test_backend  # type: ignore[attr-defined]
    rule_suggestion_client.post("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    assert fake.call_count == 1
    rule_suggestion_client.delete("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    # Next post hits the backend again because the cache was invalidated.
    rule_suggestion_client.post("/api/v1/sigma/rule-suggestions/ml:hst-anomaly:ip")
    assert fake.call_count == 2
