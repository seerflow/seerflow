"""Integration: the Splunk HEC sink against a mock HEC collector (S-362/FR-001).

Uses ``aioresponses`` to stand in for a Splunk HTTP Event Collector. The mock
asserts the four acceptance criteria end-to-end through a real
``aiohttp.ClientSession`` and the shared ``post_with_retry`` retry path:

  AC-1  HTTPS POST ``/services/collector`` with ``Authorization: Splunk <token>``
        and a ``{"event": ...}`` body.
  AC-2  ``deliver_digest`` concatenates JSON objects (NOT a JSON array); the mock
        collector parses both objects and returns success.
  AC-3  the token never appears in any log line; TLS verification is on by default.
  AC-4  5xx is retried with backoff, 4xx is logged-and-dropped (never blocks).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

import aiohttp
from aioresponses import CallbackResult, aioresponses

from seerflow.alerting.sinks.hec import HecSink
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

if TYPE_CHECKING:
    import pytest

_HEC_BASE = "https://splunk.example.com:8088"
_COLLECTOR = f"{_HEC_BASE}/services/collector"
_TOKEN = "00000000-feed-face-cafe-000000000000"


def _make_alert(*, rule_name: str = "hst-anomaly") -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.CRITICAL,
        rule_name=rule_name,
        description=f"alert: {rule_name}",
        entity_uuid="e-1",
        entity_value="10.0.0.9",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.99,
        dedup_key=f"int:{rule_name}",
    )


def _decode_concatenated_events(body: str) -> list[dict[str, Any]]:
    """Parse a HEC concatenated-JSON body into a list of event objects.

    Mirrors what a real HEC collector does: read objects back-to-back from the
    stream with a raw decoder. A JSON *array* body would raise here.
    """
    decoder = json.JSONDecoder()
    events: list[dict[str, Any]] = []
    rest = body.strip()
    while rest:
        obj, idx = decoder.raw_decode(rest)
        events.append(obj)
        rest = rest[idx:].lstrip()
    return events


# ---------------------------------------------------------------------------
# AC-1: single-event POST shape
# ---------------------------------------------------------------------------


async def test_deliver_posts_event_to_collector_with_splunk_auth() -> None:
    captured: dict[str, Any] = {}

    def _collector(url: str, **kwargs: Any) -> CallbackResult:
        captured["url"] = str(url)
        captured["headers"] = dict(kwargs.get("headers") or {})
        captured["data"] = kwargs.get("data")
        return CallbackResult(status=200, payload={"text": "Success", "code": 0})

    async with aiohttp.ClientSession() as session:
        sink = HecSink(_HEC_BASE, _TOKEN, name="splunk", session=session)
        with aioresponses() as mock:
            mock.post(_COLLECTOR, callback=_collector)
            await sink.deliver(_make_alert(rule_name="r-single"))

    assert captured["url"] == _COLLECTOR
    assert captured["url"].startswith("https://")
    assert captured["headers"]["Authorization"] == f"Splunk {_TOKEN}"
    assert captured["headers"]["Content-Type"] == "application/json"
    body = json.loads(captured["data"])
    assert body == {"event": body["event"]}
    assert body["event"]["rule_name"] == "r-single"


# ---------------------------------------------------------------------------
# AC-2: concatenated batch (not an array), accepted by the mock collector
# ---------------------------------------------------------------------------


async def test_deliver_digest_concatenates_events() -> None:
    captured: dict[str, Any] = {}

    def _collector(url: str, **kwargs: Any) -> CallbackResult:
        raw = kwargs.get("data")
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        # The mock collector parses the concatenated stream — a JSON array body
        # would raise and the test would fail, which is the point.
        events = _decode_concatenated_events(text)
        captured["events"] = events
        captured["raw"] = text
        return CallbackResult(status=200, payload={"text": "Success", "code": 0})

    async with aiohttp.ClientSession() as session:
        sink = HecSink(_HEC_BASE, _TOKEN, name="splunk", session=session)
        with aioresponses() as mock:
            mock.post(_COLLECTOR, callback=_collector)
            await sink.deliver_digest([_make_alert(rule_name="a"), _make_alert(rule_name="b")])

    assert not captured["raw"].lstrip().startswith("[")  # NOT a JSON array
    assert len(captured["events"]) == 2
    rules = {e["event"]["rule_name"] for e in captured["events"]}
    assert rules == {"a", "b"}


# ---------------------------------------------------------------------------
# AC-3: token never logged; TLS verify on by default
# ---------------------------------------------------------------------------


async def test_token_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    async with aiohttp.ClientSession() as session:
        sink = HecSink(_HEC_BASE, _TOKEN, name="splunk", session=session)
        with (
            aioresponses() as mock,
            caplog.at_level(logging.DEBUG, logger="seerflow"),
        ):
            # Force the error path (5xx exhaustion) so the most log lines emit.
            for _ in range(3):
                mock.post(_COLLECTOR, status=500, body="server error")
            await sink.deliver(_make_alert())

    rendered = " ".join(r.getMessage() for r in caplog.records)
    assert _TOKEN not in rendered


def test_tls_verification_on_by_default() -> None:
    """No CA configured → no custom SSL context → aiohttp default verification."""
    sink = HecSink(_HEC_BASE, _TOKEN, name="splunk")
    assert sink._ssl_context is None


# ---------------------------------------------------------------------------
# AC-4: retry/backoff, never blocks the pipeline
# ---------------------------------------------------------------------------


async def test_retries_on_5xx_then_succeeds() -> None:
    calls = 0

    def _collector(url: str, **kwargs: Any) -> CallbackResult:
        nonlocal calls
        calls += 1
        if calls < 2:
            return CallbackResult(status=503, body="busy")
        return CallbackResult(status=200, payload={"text": "Success", "code": 0})

    async with aiohttp.ClientSession() as session:
        sink = HecSink(_HEC_BASE, _TOKEN, name="splunk", session=session, retry_delays=(0.0, 0.0))
        with aioresponses() as mock:
            mock.post(_COLLECTOR, callback=_collector)
            mock.post(_COLLECTOR, callback=_collector)
            await sink.deliver(_make_alert())

    assert calls == 2


async def test_4xx_not_retried_and_does_not_raise() -> None:
    calls = 0

    def _collector(url: str, **kwargs: Any) -> CallbackResult:
        nonlocal calls
        calls += 1
        return CallbackResult(status=400, body="bad token")

    async with aiohttp.ClientSession() as session:
        sink = HecSink(_HEC_BASE, _TOKEN, name="splunk", session=session, retry_delays=(0.0, 0.0))
        with aioresponses() as mock:
            mock.post(_COLLECTOR, callback=_collector)
            # Must not raise — a delivery failure can never crash the pipeline.
            await sink.deliver(_make_alert())

    assert calls == 1
