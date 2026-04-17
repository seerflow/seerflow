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
    resp_mock = MagicMock(status=status)
    resp_mock.text = AsyncMock(return_value="")
    resp_cm = AsyncMock()
    resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
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


class TestPDResponseBodyLogging:
    @pytest.mark.asyncio
    async def test_4xx_reads_response_body(self) -> None:
        """On 4xx, PD sink reads response body via text() for logging."""
        resp_mock = MagicMock(status=400)
        resp_mock.text = AsyncMock(return_value="Invalid routing key")

        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
        resp_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        from seerflow.alerting.sinks.pagerduty import PagerDutySink

        sink = PagerDutySink(routing_key="key", session=session)
        sink.enqueue_trigger(_make_alert())
        await sink.stop()
        await asyncio.wait_for(sink.run(), timeout=5.0)

        resp_mock.text.assert_called_once()

    @pytest.mark.asyncio
    async def test_5xx_reads_response_body(self) -> None:
        """On 5xx, PD sink reads response body via text() for logging."""
        resp_mock = MagicMock(status=500)
        resp_mock.text = AsyncMock(return_value="Internal Server Error")

        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
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

        assert resp_mock.text.call_count == 3  # 3 retries


class TestPostResolve:
    async def test_success_on_200_no_retry(self) -> None:
        from seerflow.alerting.sinks.pagerduty import post_resolve

        session = _mock_session(status=200)
        await post_resolve(session, "dedup-1", "routing-key")
        assert session.post.call_count == 1

    async def test_retry_once_on_500_then_give_up(self) -> None:
        from seerflow.alerting.sinks.pagerduty import post_resolve

        session = _mock_session(status=500)
        await post_resolve(session, "dedup-1", "routing-key", delays=(0.0,))
        assert session.post.call_count == 2

    async def test_no_retry_on_400(self) -> None:
        from seerflow.alerting.sinks.pagerduty import post_resolve

        session = _mock_session(status=400)
        await post_resolve(session, "dedup-1", "routing-key")
        assert session.post.call_count == 1

    async def test_retry_on_network_error(self) -> None:
        from seerflow.alerting.sinks.pagerduty import post_resolve

        session = MagicMock()
        session.post = MagicMock(side_effect=ConnectionError("boom"))

        await post_resolve(session, "dedup-1", "routing-key", delays=(0.0,))
        assert session.post.call_count == 2

    async def test_payload_reuses_build_resolve_payload(self) -> None:
        """The helper must POST to _PD_ENDPOINT with the _build_resolve_payload output."""
        from seerflow.alerting.sinks.pagerduty import (
            _PD_ENDPOINT,
            _build_resolve_payload,
            post_resolve,
        )

        session = _mock_session(status=200)
        await post_resolve(session, "dedup-42", "rk-abc")

        args, kwargs = session.post.call_args
        assert args[0] == _PD_ENDPOINT
        assert kwargs["json"] == _build_resolve_payload("dedup-42", "rk-abc")

    async def test_typeerror_propagates_not_swallowed(self) -> None:
        """Unexpected bugs (TypeError, AttributeError) must surface, not be retried."""
        from seerflow.alerting.sinks.pagerduty import post_resolve

        session = MagicMock()
        session.post = MagicMock(side_effect=TypeError("programmer error"))

        with pytest.raises(TypeError, match="programmer error"):
            await post_resolve(session, "dedup-1", "routing-key", delays=(0.0,))

        # Bug propagated on the first attempt — no retry occurred.
        assert session.post.call_count == 1

    async def test_exhaustion_log_truncates_dedup_key_to_8_chars(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """After all retries, the exhaustion log leaks at most 8 chars of dedup_key."""
        import logging

        from seerflow.alerting.sinks.pagerduty import post_resolve

        session = _mock_session(status=500)
        full_key = "ml:hst-anomaly:entity-uuid-001"  # 30 chars; rule_name is PII-ish.

        with caplog.at_level(logging.ERROR, logger="seerflow"):
            await post_resolve(
                session,
                full_key,
                "routing-key",
                delays=(0.0,),
            )

        exhaustion = [r for r in caplog.records if "attempts exhausted" in r.message]
        assert exhaustion, "expected one exhaustion log record"
        message = exhaustion[0].getMessage()

        # First 8 chars appear; full rule_name + entity_uuid do not.
        assert full_key[:8] in message
        assert "hst-anomaly" not in message
        assert "entity-uuid-001" not in message

    async def test_exhaustion_log_no_ellipsis_for_short_dedup_key(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When dedup_key is <= 8 chars, the exhaustion log MUST NOT append '...'.

        The ellipsis signals truncation; emitting it for an untruncated key would mislead
        log parsers that detect truncated identifiers by the literal suffix.
        """
        import logging

        from seerflow.alerting.sinks.pagerduty import post_resolve

        session = _mock_session(status=500)
        short_key = "fp:rate"  # 7 chars — fully visible, no truncation.

        with caplog.at_level(logging.ERROR, logger="seerflow"):
            await post_resolve(session, short_key, "routing-key", delays=(0.0,))

        exhaustion = [r for r in caplog.records if "attempts exhausted" in r.message]
        assert exhaustion, "expected one exhaustion log record"
        message = exhaustion[0].getMessage()
        assert short_key in message
        assert "..." not in message

    async def test_asyncio_timeout_error_is_retried(self) -> None:
        """A raw asyncio.TimeoutError must be caught and retried (same class as builtin
        TimeoutError in Python 3.11+, but pinning the behaviour explicitly)."""
        from seerflow.alerting.sinks.pagerduty import post_resolve

        session = MagicMock()
        session.post = MagicMock(side_effect=TimeoutError("timeout"))

        await post_resolve(session, "dedup-1", "routing-key", delays=(0.0,))

        # 2 attempts (default max_retries), both raised TimeoutError and were caught+retried.
        assert session.post.call_count == 2
