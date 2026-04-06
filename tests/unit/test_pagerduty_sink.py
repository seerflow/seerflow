"""Tests for PagerDutySink: severity mapping, payload formatting, queue, retry."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_alert(
    *,
    severity_id: SeverityLevel = SeverityLevel.ERROR,
    rule_name: str = "hst-anomaly",
    alert_type: str = "ml",
    entity_uuid: str = "entity-uuid-001",
    entity_value: str = "10.0.0.1",
    mitre_tactics: tuple[str, ...] = (),
    mitre_techniques: tuple[str, ...] = (),
) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=severity_id,
        rule_name=rule_name,
        description=f"Test alert: {rule_name}",
        entity_uuid=entity_uuid,
        entity_value=entity_value,
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.85,
        dedup_key=f"test:{rule_name}",
        mitre_tactics=mitre_tactics,
        mitre_techniques=mitre_techniques,
    )


def _mock_session(status: int = 200) -> MagicMock:
    """Return a mock aiohttp.ClientSession that returns `status` on POST."""
    resp_cm = AsyncMock()
    resp_cm.__aenter__ = AsyncMock(return_value=MagicMock(status=status))
    resp_cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=resp_cm)
    return session


# ---------------------------------------------------------------------------
# Severity mapping tests
# ---------------------------------------------------------------------------


class TestSeverityMapping:
    def test_critical_maps_to_critical(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _map_severity

        assert _map_severity(SeverityLevel.CRITICAL) == "critical"

    def test_fatal_maps_to_critical(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _map_severity

        assert _map_severity(SeverityLevel.FATAL) == "critical"

    def test_error_maps_to_error(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _map_severity

        assert _map_severity(SeverityLevel.ERROR) == "error"

    def test_warning_maps_to_warning(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _map_severity

        assert _map_severity(SeverityLevel.WARNING) == "warning"

    def test_notice_maps_to_warning(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _map_severity

        assert _map_severity(SeverityLevel.NOTICE) == "warning"

    def test_informational_maps_to_info(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _map_severity

        assert _map_severity(SeverityLevel.INFORMATIONAL) == "info"

    def test_trace_maps_to_info(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _map_severity

        assert _map_severity(SeverityLevel.TRACE) == "info"


# ---------------------------------------------------------------------------
# Trigger payload tests
# ---------------------------------------------------------------------------


class TestTriggerPayload:
    def test_trigger_payload_structure(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _build_trigger_payload

        alert = _make_alert()
        payload = _build_trigger_payload(alert, "test-routing-key")
        assert payload["routing_key"] == "test-routing-key"
        assert payload["event_action"] == "trigger"
        assert "dedup_key" in payload
        assert "payload" in payload

    def test_dedup_key_format(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _build_trigger_payload

        alert = _make_alert(alert_type="ml", rule_name="hst-anomaly", entity_uuid="ent-123")
        payload = _build_trigger_payload(alert, "key")
        assert payload["dedup_key"] == "ml:hst-anomaly:ent-123"

    def test_custom_details_contains_alert_fields(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _build_trigger_payload

        alert = _make_alert(
            mitre_tactics=("TA0001",),
            mitre_techniques=("T1078",),
        )
        payload = _build_trigger_payload(alert, "key")
        details = payload["payload"]["custom_details"]  # type: ignore[index]
        assert details["rule_name"] == "hst-anomaly"
        assert details["entity_value"] == "10.0.0.1"
        assert details["mitre_tactics"] == ["TA0001"]
        assert details["mitre_techniques"] == ["T1078"]
        assert details["risk_score"] == 0.85

    def test_payload_source_is_seerflow(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _build_trigger_payload

        alert = _make_alert()
        payload = _build_trigger_payload(alert, "key")
        assert payload["payload"]["source"] == "seerflow"  # type: ignore[index]

    def test_severity_in_payload(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _build_trigger_payload

        alert = _make_alert(severity_id=SeverityLevel.CRITICAL)
        payload = _build_trigger_payload(alert, "key")
        assert payload["payload"]["severity"] == "critical"  # type: ignore[index]

    def test_timestamp_is_iso8601(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _build_trigger_payload

        alert = _make_alert()
        payload = _build_trigger_payload(alert, "key")
        ts = payload["payload"]["timestamp"]  # type: ignore[index]
        assert "T" in ts
        assert ts.endswith("+00:00") or ts.endswith("Z")

    def test_summary_contains_description_and_rule(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _build_trigger_payload

        alert = _make_alert(rule_name="sigma-brute-force")
        payload = _build_trigger_payload(alert, "key")
        summary = payload["payload"]["summary"]  # type: ignore[index]
        assert "sigma-brute-force" in summary

    def test_contributing_events_serialized_as_strings(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _build_trigger_payload

        alert = _make_alert()
        payload = _build_trigger_payload(alert, "key")
        events = payload["payload"]["custom_details"]["contributing_events"]  # type: ignore[index]
        assert isinstance(events, list)
        assert all(isinstance(e, str) for e in events)


# ---------------------------------------------------------------------------
# Resolve payload tests
# ---------------------------------------------------------------------------


class TestResolvePayload:
    def test_resolve_payload_structure(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _build_resolve_payload

        payload = _build_resolve_payload("ml:hst-anomaly:ent-123", "test-key")
        assert payload["routing_key"] == "test-key"
        assert payload["event_action"] == "resolve"
        assert payload["dedup_key"] == "ml:hst-anomaly:ent-123"
        assert "payload" not in payload

    def test_resolve_dedup_key_round_trips(self) -> None:
        from seerflow.alerting.sinks.pagerduty import _build_resolve_payload

        dedup_key = "sigma:lateral-movement:host-001"
        payload = _build_resolve_payload(dedup_key, "key")
        assert payload["dedup_key"] == dedup_key


# ---------------------------------------------------------------------------
# PagerDutySink async tests
# ---------------------------------------------------------------------------


class TestPagerDutySinkAsync:
    @pytest.mark.asyncio
    async def test_enqueue_trigger_and_dispatch(self) -> None:
        session = _mock_session(202)
        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="test-key", session=session)
        alert = _make_alert()
        sink.enqueue_trigger(alert)
        await sink.stop()
        await asyncio.wait_for(sink.run(), timeout=5.0)
        session.post.assert_called_once()
        call_kwargs = session.post.call_args
        assert call_kwargs[1]["json"]["event_action"] == "trigger"

    @pytest.mark.asyncio
    async def test_enqueue_resolve_and_dispatch(self) -> None:
        session = _mock_session(202)
        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="test-key", session=session)
        sink.enqueue_resolve("ml:hst-anomaly:ent-123")
        await sink.stop()
        await asyncio.wait_for(sink.run(), timeout=5.0)
        call_kwargs = session.post.call_args
        assert call_kwargs[1]["json"]["event_action"] == "resolve"
        assert call_kwargs[1]["json"]["dedup_key"] == "ml:hst-anomaly:ent-123"

    @pytest.mark.asyncio
    async def test_queue_full_drops_trigger(self) -> None:
        session = _mock_session()
        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session, queue_maxsize=1)
        sink.enqueue_trigger(_make_alert())
        sink.enqueue_trigger(_make_alert())  # should drop silently
        assert sink._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_queue_full_logs_warning_on_trigger(self) -> None:
        session = _mock_session()
        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session, queue_maxsize=1)
        sink.enqueue_trigger(_make_alert())
        with patch("seerflow.alerting.sinks.pagerduty._log") as mock_log:
            sink.enqueue_trigger(_make_alert())
            mock_log.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_queue_full_logs_warning_on_resolve(self) -> None:
        session = _mock_session()
        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session, queue_maxsize=1)
        sink.enqueue_trigger(_make_alert())
        with patch("seerflow.alerting.sinks.pagerduty._log") as mock_log:
            sink.enqueue_resolve("ml:hst-anomaly:ent-123")
            mock_log.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_server_error(self) -> None:
        resp_fail = AsyncMock()
        resp_fail.__aenter__ = AsyncMock(return_value=MagicMock(status=500))
        resp_fail.__aexit__ = AsyncMock(return_value=False)
        resp_ok = AsyncMock()
        resp_ok.__aenter__ = AsyncMock(return_value=MagicMock(status=202))
        resp_ok.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(side_effect=[resp_fail, resp_ok])

        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session)
        sink.enqueue_trigger(_make_alert())
        await sink.stop()

        with patch("seerflow.alerting.sinks.pagerduty.asyncio") as mock_asyncio:
            mock_asyncio.Queue = asyncio.Queue
            mock_asyncio.QueueFull = asyncio.QueueFull
            mock_asyncio.wait_for = asyncio.wait_for
            mock_asyncio.sleep = AsyncMock()
            await asyncio.wait_for(sink.run(), timeout=5.0)

        assert session.post.call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_client_error(self) -> None:
        session = _mock_session(400)
        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session)
        sink.enqueue_trigger(_make_alert())
        await sink.stop()
        await asyncio.wait_for(sink.run(), timeout=5.0)
        assert session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_exhausts_retries_on_persistent_500(self) -> None:
        session = _mock_session(500)
        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session)
        sink.enqueue_trigger(_make_alert())
        await sink.stop()

        with patch("seerflow.alerting.sinks.pagerduty.asyncio") as mock_asyncio:
            mock_asyncio.Queue = asyncio.Queue
            mock_asyncio.QueueFull = asyncio.QueueFull
            mock_asyncio.wait_for = asyncio.wait_for
            mock_asyncio.sleep = AsyncMock()
            await asyncio.wait_for(sink.run(), timeout=5.0)

        assert session.post.call_count == 3

    @pytest.mark.asyncio
    async def test_routing_key_not_logged(self) -> None:
        """Ensure routing_key does not appear in log output."""
        session = _mock_session(500)
        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="super-secret-key-12345", session=session)
        sink.enqueue_trigger(_make_alert())
        await sink.stop()

        with (
            patch("seerflow.alerting.sinks.pagerduty.asyncio") as mock_asyncio,
            patch("seerflow.alerting.sinks.pagerduty._log") as mock_log,
        ):
            mock_asyncio.Queue = asyncio.Queue
            mock_asyncio.QueueFull = asyncio.QueueFull
            mock_asyncio.wait_for = asyncio.wait_for
            mock_asyncio.sleep = AsyncMock()
            await asyncio.wait_for(sink.run(), timeout=5.0)

        for call in mock_log.warning.call_args_list + mock_log.error.call_args_list:
            msg = str(call)
            assert "super-secret-key-12345" not in msg

    @pytest.mark.asyncio
    async def test_stop_drains_queue(self) -> None:
        session = _mock_session(202)
        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session)
        for i in range(3):
            sink.enqueue_trigger(_make_alert(rule_name=f"rule-{i}"))
        await sink.stop()
        await asyncio.wait_for(sink.run(), timeout=5.0)
        assert session.post.call_count == 3

    @pytest.mark.asyncio
    async def test_exception_during_post_retried(self) -> None:
        """Network exception during POST is retried up to MAX_RETRIES."""
        call_count = 0

        async def fake_aenter(_self: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("connection refused")
            return MagicMock(status=202)

        resp_cm = MagicMock()
        resp_cm.__aenter__ = fake_aenter
        resp_cm.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session)
        sink.enqueue_trigger(_make_alert())
        await sink.stop()

        with patch("seerflow.alerting.sinks.pagerduty.asyncio") as mock_asyncio:
            mock_asyncio.Queue = asyncio.Queue
            mock_asyncio.QueueFull = asyncio.QueueFull
            mock_asyncio.wait_for = asyncio.wait_for
            mock_asyncio.sleep = AsyncMock()
            await asyncio.wait_for(sink.run(), timeout=5.0)

        assert session.post.call_count == 3

    @pytest.mark.asyncio
    async def test_post_uses_allow_redirects_false(self) -> None:
        """POST is made with allow_redirects=False."""
        session = _mock_session(202)
        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session)
        sink.enqueue_trigger(_make_alert())
        await sink.stop()
        await asyncio.wait_for(sink.run(), timeout=5.0)
        call_kwargs = session.post.call_args[1]
        assert call_kwargs.get("allow_redirects") is False

    @pytest.mark.asyncio
    async def test_post_targets_pd_endpoint(self) -> None:
        """POST is made to the PagerDuty Events API v2 endpoint."""
        session = _mock_session(202)
        from seerflow.alerting.sinks.pagerduty import _PD_ENDPOINT, PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session)
        sink.enqueue_trigger(_make_alert())
        await sink.stop()
        await asyncio.wait_for(sink.run(), timeout=5.0)
        call_args = session.post.call_args[0][0]
        assert call_args == _PD_ENDPOINT
