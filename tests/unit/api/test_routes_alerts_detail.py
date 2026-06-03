"""Unit tests for the alert-detail endpoint contributing-events enrichment (S-338).

Covers:
  * ``entity_path_for`` precedence (users → hosts → ips).
  * ``ContributingEventResponse.from_event`` field mapping.
  * Full route round-trip through ``TestClient`` with a stub LogStore /
    AlertStore proving the new ``contributing_events`` payload is hydrated
    with ``severity_text`` + ``entity_path``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.api.schemas import ContributingEventResponse, entity_path_for
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.query import Page

if TYPE_CHECKING:
    from collections.abc import Iterable


# ── Stubs ────────────────────────────────────────────────────────────────────


class _StubAlertStore:
    """Minimal AlertStore stub honouring ``get_alert_by_id``."""

    def __init__(self, alerts: Iterable[Alert]) -> None:
        self._alerts = {a.alert_id: a for a in alerts}

    async def get_alert_by_id(self, alert_id: str) -> Alert | None:
        return self._alerts.get(alert_id)

    # The route also calls list_feedback_events / update_feedback in other
    # tests; those are not exercised here.


class _StubLogStore:
    """Minimal LogStore stub honouring ``query_events`` for hydration."""

    def __init__(self, events: Iterable[SeerflowEvent]) -> None:
        self.events: tuple[SeerflowEvent, ...] = tuple(events)
        self.calls: list[object] = []

    async def query_events(self, query: object) -> Page[SeerflowEvent]:
        # Capture the query so tests can assert lookback shape if needed.
        self.calls.append(query)
        return Page(
            items=self.events,
            total=len(self.events),
            page=1,
            limit=100,
        )


def _build_event(
    *,
    event_id: uuid.UUID,
    severity: SeverityLevel = SeverityLevel.WARNING,
    users: tuple[str, ...] = (),
    hosts: tuple[str, ...] = (),
    ips: tuple[str, ...] = (),
    message: str = "evt msg",
    timestamp_ns: int = 1_700_000_000_000_000_000,
) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=event_id,
        timestamp_ns=timestamp_ns,
        observed_ns=timestamp_ns + 1,
        message=message,
        source_type="syslog",
        severity_id=severity,
        related_users=users,
        related_hosts=hosts,
        related_ips=ips,
    )


def _build_alert(*, alert_id: str, contributing: tuple[uuid.UUID, ...]) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type="sigma",
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.ERROR,
        rule_name="rule.test",
        description="alert description",
        entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, "ws-attack-01")),
        entity_value="ws-attack-01",
        entity_type="host",
        contributing_events=contributing,
        risk_score=0.6,
    )


# ── entity_path_for precedence ───────────────────────────────────────────────


class TestEntityPathFor:
    def test_users_take_precedence_when_both_present(self) -> None:
        ev = _build_event(
            event_id=uuid.uuid4(),
            users=("alice", "bob"),
            hosts=("hostA",),
        )
        assert entity_path_for(ev) == {"src": "alice", "dst": "bob"}

    def test_falls_back_to_hosts_when_no_users(self) -> None:
        ev = _build_event(
            event_id=uuid.uuid4(),
            hosts=("ws-attack-01", "fileshare-01"),
        )
        assert entity_path_for(ev) == {"src": "ws-attack-01", "dst": "fileshare-01"}

    def test_falls_back_to_ips_when_no_users_no_hosts(self) -> None:
        ev = _build_event(
            event_id=uuid.uuid4(),
            ips=("10.0.0.1", "10.0.0.2"),
        )
        assert entity_path_for(ev) == {"src": "10.0.0.1", "dst": "10.0.0.2"}

    def test_dst_omitted_when_only_one_value(self) -> None:
        ev = _build_event(event_id=uuid.uuid4(), users=("alice",))
        assert entity_path_for(ev) == {"src": "alice", "dst": None}

    def test_returns_empty_when_no_entities(self) -> None:
        ev = _build_event(event_id=uuid.uuid4())
        # The helper must not raise — empty result triggers omission upstream.
        assert entity_path_for(ev) == {"src": None, "dst": None}


# ── ContributingEventResponse.from_event ─────────────────────────────────────


class TestContributingEventResponse:
    def test_maps_all_enrichment_fields(self) -> None:
        eid = uuid.uuid4()
        ev = _build_event(
            event_id=eid,
            severity=SeverityLevel.CRITICAL,
            users=("svc-attacker", "victim"),
            message="lsass.exe memory read",
        )
        out = ContributingEventResponse.from_event(ev)
        assert out.event_id == str(eid)
        assert out.timestamp_ns == ev.timestamp_ns
        assert out.message == "lsass.exe memory read"
        assert out.severity_text == "Critical"
        assert out.entity_path == {"src": "svc-attacker", "dst": "victim"}

    def test_timestamp_serialises_as_string_for_js_bigint_safety(self) -> None:
        ev = _build_event(event_id=uuid.uuid4(), users=("u",))
        out = ContributingEventResponse.from_event(ev)
        dumped = out.model_dump(mode="json")
        assert isinstance(dumped["timestamp_ns"], str)


# ── Route-level hydration ────────────────────────────────────────────────────


@pytest.fixture
def hydrated_route_client() -> tuple[TestClient, _StubLogStore, uuid.UUID, str]:
    """Wire a TestClient with stubs carrying one alert + 2 matching events.

    Returns the client, the log store stub (for call introspection), the
    first event id (so callers can assert it was selected), and the alert id.
    """
    eid_a = uuid.uuid4()
    eid_b = uuid.uuid4()
    eid_unrelated = uuid.uuid4()  # in the store but NOT in alert.contributing_events
    alert = _build_alert(alert_id="alrt-338-1", contributing=(eid_a, eid_b))
    events = (
        _build_event(
            event_id=eid_a,
            severity=SeverityLevel.CRITICAL,
            users=("svc-attacker", "victim"),
            message="LSASS memory dump",
        ),
        _build_event(
            event_id=eid_b,
            severity=SeverityLevel.WARNING,
            hosts=("ws-attack-01",),
            message="suspicious registry read",
        ),
        _build_event(
            event_id=eid_unrelated,
            severity=SeverityLevel.INFORMATIONAL,
            users=("noise",),
            message="should not appear",
        ),
    )
    log_store = _StubLogStore(events)
    alert_store = _StubAlertStore([alert])
    app = create_api_app(log_store=log_store, alert_store=alert_store)
    return TestClient(app), log_store, eid_a, alert.alert_id


class TestAlertDetailHydration:
    def test_response_includes_hydrated_contributing_events(
        self, hydrated_route_client: tuple[TestClient, _StubLogStore, uuid.UUID, str]
    ) -> None:
        client, _, eid_a, alert_id = hydrated_route_client
        resp = client.get(f"/api/v1/alerts/{alert_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "contributing_events" in body, "must hydrate the new field"
        ce = body["contributing_events"]
        assert isinstance(ce, list)
        assert len(ce) == 2, "only events that appear in alert.contributing_events"
        # Order does not matter for the API contract; assert membership.
        ids = {row["event_id"] for row in ce}
        assert str(eid_a) in ids

    def test_each_row_carries_severity_text_and_entity_path(
        self, hydrated_route_client: tuple[TestClient, _StubLogStore, uuid.UUID, str]
    ) -> None:
        client, _, eid_a, alert_id = hydrated_route_client
        resp = client.get(f"/api/v1/alerts/{alert_id}")
        body = resp.json()
        row_a = next(r for r in body["contributing_events"] if r["event_id"] == str(eid_a))
        assert row_a["severity_text"] == "Critical"
        assert row_a["entity_path"] == {"src": "svc-attacker", "dst": "victim"}
        # Bigint safety: timestamp_ns must be a JSON string.
        assert isinstance(row_a["timestamp_ns"], str)

    def test_omits_unrelated_events_from_the_lookup_window(
        self, hydrated_route_client: tuple[TestClient, _StubLogStore, uuid.UUID, str]
    ) -> None:
        client, _, _, alert_id = hydrated_route_client
        resp = client.get(f"/api/v1/alerts/{alert_id}")
        body = resp.json()
        messages = {r["message"] for r in body["contributing_events"]}
        assert "should not appear" not in messages

    def test_empty_contributing_events_omits_the_field(self) -> None:
        alert = _build_alert(alert_id="alrt-338-empty", contributing=())
        log_store = _StubLogStore(())
        alert_store = _StubAlertStore([alert])
        app = create_api_app(log_store=log_store, alert_store=alert_store)
        client = TestClient(app)
        resp = client.get(f"/api/v1/alerts/{alert.alert_id}")
        assert resp.status_code == 200
        body = resp.json()
        # Either omitted entirely or present as an empty list — both are
        # acceptable as long as the frontend tolerates them. We assert the
        # field, if present, is not truthy with stale rows.
        assert not body.get("contributing_events")

    def test_no_events_found_falls_back_gracefully(self) -> None:
        # Alert references uuids that the log store doesn't carry → no crash,
        # field omitted / empty rather than a 500.
        alert = _build_alert(alert_id="alrt-338-miss", contributing=(uuid.uuid4(),))
        log_store = _StubLogStore(())
        alert_store = _StubAlertStore([alert])
        app = create_api_app(log_store=log_store, alert_store=alert_store)
        client = TestClient(app)
        resp = client.get(f"/api/v1/alerts/{alert.alert_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert not body.get("contributing_events")
