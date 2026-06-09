"""Unit tests for the Splunk HEC outbound sink (S-362/FR-001)."""

from __future__ import annotations

import json
import ssl
import uuid
from unittest.mock import AsyncMock, patch

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_alert(*, rule_name: str = "hst-anomaly") -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.ERROR,
        rule_name=rule_name,
        description=f"Test alert: {rule_name}",
        entity_uuid="entity-uuid-001",
        entity_value="10.0.0.1",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.85,
        dedup_key=f"test:{rule_name}",
    )


# ---------------------------------------------------------------------------
# Body construction
# ---------------------------------------------------------------------------


class TestBuildEventBody:
    def test_wraps_alert_json_in_event_key(self) -> None:
        from seerflow.alerting.sinks.hec import _build_event_body

        body = _build_event_body(_make_alert(rule_name="r1"))
        assert set(body.keys()) == {"event"}
        assert body["event"]["rule_name"] == "r1"
        assert body["event"]["entity_value"] == "10.0.0.1"

    def test_event_is_json_serializable(self) -> None:
        from seerflow.alerting.sinks.hec import _build_event_body

        body = _build_event_body(_make_alert())
        # Round-trips without error.
        assert json.loads(json.dumps(body))["event"]["alert_type"] == "ml"


class TestConcatenateEvents:
    def test_concatenates_objects_without_array(self) -> None:
        from seerflow.alerting.sinks.hec import _concatenate_events

        raw = _concatenate_events([_make_alert(rule_name="a"), _make_alert(rule_name="b")])
        text = raw.decode("utf-8")
        # HEC wants concatenated JSON objects, NOT a JSON array.
        assert not text.lstrip().startswith("[")
        assert text.count('"event"') == 2
        # The boundary between objects is ``}{`` (compact, no separator/array).
        assert "}{" in text

    def test_each_object_is_valid_event_json(self) -> None:
        from seerflow.alerting.sinks.hec import _concatenate_events

        raw = _concatenate_events([_make_alert(rule_name="solo")])
        obj = json.loads(raw.decode("utf-8"))
        assert obj["event"]["rule_name"] == "solo"

    def test_two_objects_decode_via_raw_decoder(self) -> None:
        from seerflow.alerting.sinks.hec import _concatenate_events

        raw = _concatenate_events([_make_alert(rule_name="x"), _make_alert(rule_name="y")])
        text = raw.decode("utf-8")
        decoder = json.JSONDecoder()
        first, idx = decoder.raw_decode(text)
        second, _ = decoder.raw_decode(text[idx:].lstrip())
        assert first["event"]["rule_name"] == "x"
        assert second["event"]["rule_name"] == "y"


# ---------------------------------------------------------------------------
# Endpoint + masking
# ---------------------------------------------------------------------------


class TestEndpointAndMask:
    def test_collector_url_appended(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sink = HecSink("https://splunk.example.com:8088", "tok", name="splunk")
        assert sink._collector_url == "https://splunk.example.com:8088/services/collector"

    def test_collector_url_strips_trailing_slash(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sink = HecSink("https://splunk.example.com:8088/", "tok", name="splunk")
        assert sink._collector_url == "https://splunk.example.com:8088/services/collector"

    def test_masked_endpoint_hides_token_and_path(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sink = HecSink("https://splunk.example.com:8088", "tok", name="splunk")
        masked = sink._masked
        assert "tok" not in masked
        assert masked == "https://splunk.example.com:8088/***"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_delivery_target(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink
        from seerflow.alerting.target import DeliveryTarget

        sink = HecSink("https://h:8088", "tok", name="s", min_severity=3)
        assert isinstance(sink, DeliveryTarget)
        assert sink.name == "s"
        assert sink.min_severity == 3


# ---------------------------------------------------------------------------
# deliver / deliver_digest behaviour (mocked post_with_retry)
# ---------------------------------------------------------------------------


class TestDeliver:
    async def test_deliver_posts_single_event_with_splunk_auth(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sink = HecSink("https://splunk:8088", "s3cr3t", name="splunk")
        with patch("seerflow.alerting.sinks.hec.post_with_retry", new=AsyncMock()) as mock_post:
            await sink.deliver(_make_alert(rule_name="r-single"))

        mock_post.assert_awaited_once()
        kwargs = mock_post.await_args.kwargs
        args = mock_post.await_args.args
        url = args[1] if len(args) > 1 else kwargs["url"]
        assert url == "https://splunk:8088/services/collector"
        assert kwargs["headers"]["Authorization"] == "Splunk s3cr3t"
        assert kwargs["headers"]["Content-Type"] == "application/json"
        body = json.loads(kwargs["data"])
        assert body["event"]["rule_name"] == "r-single"

    async def test_deliver_masks_endpoint_for_logging(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sink = HecSink("https://splunk:8088", "s3cr3t", name="splunk")
        with patch("seerflow.alerting.sinks.hec.post_with_retry", new=AsyncMock()) as mock_post:
            await sink.deliver(_make_alert())

        masked = mock_post.await_args.kwargs["masked_for_log"]
        assert "s3cr3t" not in masked
        assert masked == "https://splunk:8088/***"


class TestDeliverDigest:
    async def test_digest_concatenates_objects_single_post(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sink = HecSink("https://splunk:8088", "tok", name="splunk")
        with patch("seerflow.alerting.sinks.hec.post_with_retry", new=AsyncMock()) as mock_post:
            await sink.deliver_digest([_make_alert(rule_name="a"), _make_alert(rule_name="b")])

        # A single POST carries the whole batch — NOT one POST per alert.
        mock_post.assert_awaited_once()
        body = mock_post.await_args.kwargs["data"].decode("utf-8")
        assert body.count('"event"') == 2
        assert not body.lstrip().startswith("[")

    async def test_digest_empty_is_noop(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sink = HecSink("https://splunk:8088", "tok", name="splunk")
        with patch("seerflow.alerting.sinks.hec.post_with_retry", new=AsyncMock()) as mock_post:
            await sink.deliver_digest([])
        mock_post.assert_not_awaited()


# ---------------------------------------------------------------------------
# TLS / CA bundle
# ---------------------------------------------------------------------------


class TestTls:
    def test_no_ca_means_no_ssl_context(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sink = HecSink("https://splunk:8088", "tok", name="splunk")
        assert sink._ssl_context is None

    def test_ca_builds_ssl_context(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sentinel = ssl.create_default_context()
        with patch(
            "seerflow.alerting.sinks.hec.ssl.create_default_context", return_value=sentinel
        ) as factory:
            sink = HecSink("https://splunk:8088", "tok", name="splunk", ca="/path/ca.pem")
        factory.assert_called_once_with(cafile="/path/ca.pem")
        assert sink._ssl_context is sentinel

    async def test_ssl_context_passed_to_post(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sentinel = ssl.create_default_context()
        with patch(
            "seerflow.alerting.sinks.hec.ssl.create_default_context", return_value=sentinel
        ):
            sink = HecSink("https://splunk:8088", "tok", name="splunk", ca="/some/ca.pem")
        assert sink._ssl_context is sentinel
        with patch("seerflow.alerting.sinks.hec.post_with_retry", new=AsyncMock()) as mock_post:
            await sink.deliver(_make_alert())
        assert mock_post.await_args.kwargs["ssl_context"] is sentinel

    async def test_no_ssl_context_omitted_from_post(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sink = HecSink("https://splunk:8088", "tok", name="splunk")
        with patch("seerflow.alerting.sinks.hec.post_with_retry", new=AsyncMock()) as mock_post:
            await sink.deliver(_make_alert())
        # ssl_context kwarg is None (aiohttp default verification) when no CA set.
        assert mock_post.await_args.kwargs["ssl_context"] is None


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    async def test_lazily_creates_session_when_none_given(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        fake_session = AsyncMock()
        sink = HecSink("https://splunk:8088", "tok", name="splunk")
        with (
            patch("seerflow.alerting.sinks.hec.aiohttp.ClientSession", return_value=fake_session),
            patch("seerflow.alerting.sinks.hec.post_with_retry", new=AsyncMock()),
        ):
            await sink.deliver(_make_alert())
            assert sink._session is fake_session
            await sink.close()
        fake_session.close.assert_awaited_once()
        assert sink._session is None

    async def test_close_does_not_close_injected_session(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        injected = AsyncMock()
        sink = HecSink("https://splunk:8088", "tok", name="splunk", session=injected)
        await sink.close()
        injected.close.assert_not_awaited()
        assert sink._session is injected

    async def test_close_is_noop_when_no_session(self) -> None:
        from seerflow.alerting.sinks.hec import HecSink

        sink = HecSink("https://splunk:8088", "tok", name="splunk")
        # Never delivered → no session created. close() must be a safe no-op.
        await sink.close()
        assert sink._session is None
