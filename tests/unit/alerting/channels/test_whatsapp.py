"""Tests for WhatsAppTarget — Business Cloud API template messages (S-163)."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses

from seerflow.alerting.channels.whatsapp import (
    WhatsAppTarget,
    build_template_params,
)
from seerflow.models.event import SeverityLevel
from tests.unit.alert_factory import make_alert

# --- helpers -----------------------------------------------------------------


async def _deliver_with_zero_delay(target: WhatsAppTarget, session: aiohttp.ClientSession) -> None:
    """Run target.deliver(...) with zero-delay backoff inside post_with_retry.

    `_post_one` calls the symbol `post_with_retry` that was bound at module load
    in `seerflow.alerting.channels.whatsapp`, so rebinding `_wa.post_with_retry`
    is sufficient — `_post_one` does not re-import the name on each call.
    """
    from seerflow.alerting.channels import whatsapp as _wa

    original = _wa.post_with_retry

    async def fast(*args: Any, **kwargs: Any) -> None:
        kwargs["delays"] = (0.0, 0.0, 0.0)
        await original(*args, **kwargs)

    try:
        _wa.post_with_retry = fast  # type: ignore[attr-defined]
        await target.deliver(make_alert(), session=session)
    finally:
        _wa.post_with_retry = original  # type: ignore[attr-defined]


# --- tests -------------------------------------------------------------------


@pytest.mark.unit
def test_template_params_three_text_entries() -> None:
    alert = make_alert(severity_id=SeverityLevel.CRITICAL, rule_name="brute-force")
    params = build_template_params(alert)
    assert len(params) == 3
    texts = [p["text"] for p in params]
    assert "CRITICAL" in texts
    assert "brute-force" in texts


@pytest.mark.unit
def test_whatsapp_target_hides_access_token_in_repr() -> None:
    t = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="secret-wa-token",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+15559876543",),
    )
    assert "secret-wa-token" not in repr(t)


@pytest.mark.unit
async def test_whatsapp_deliver_posts_template_message() -> None:
    target = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+15559876543",),
        rate_per_second=100.0,
        burst=10,
    )
    captured: list[dict[str, Any]] = []

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url
        captured.append(kwargs.get("json") or {})
        return CallbackResult(status=200, payload={"messages": []})

    with aioresponses() as mock:
        mock.post(
            "https://graph.facebook.com/v18.0/PID/messages",
            callback=_capture,
        )
        async with aiohttp.ClientSession() as session:
            await target.deliver(make_alert(), session=session)

    assert len(captured) == 1
    body = captured[0]
    assert body["messaging_product"] == "whatsapp"
    assert body["to"] == "+15559876543"
    assert body["template"]["name"] == "seerflow_alert"
    assert body["template"]["language"] == {"code": "en"}


@pytest.mark.unit
async def test_whatsapp_131026_opens_circuit_for_5_minutes() -> None:
    now = [0.0]

    def fake_mono() -> float:
        return now[0]

    target = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+15559876543",),
        rate_per_second=1000.0,
        burst=1000,
        _monotonic=fake_mono,
    )
    call_count = 0

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url, kwargs
        nonlocal call_count
        call_count += 1
        return CallbackResult(
            status=400,
            payload={"error": {"code": 131026, "message": "template not found"}},
        )

    with aioresponses() as mock:
        mock.post(
            "https://graph.facebook.com/v18.0/PID/messages",
            callback=_capture,
            repeat=True,
        )
        async with aiohttp.ClientSession() as session:
            # First call hits the API and opens the circuit.
            await target.deliver(make_alert(), session=session)
            assert call_count == 1
            # Circuit-open window: no HTTP call.
            now[0] = 60.0
            await target.deliver(make_alert(), session=session)
            assert call_count == 1
            # After 5 minutes, circuit closes; next call hits again.
            now[0] = 301.0
            await target.deliver(make_alert(), session=session)
            assert call_count == 2


@pytest.mark.unit
async def test_whatsapp_non_131026_400_does_not_open_circuit(
    caplog: pytest.LogCaptureFixture,
) -> None:

    target = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+1",),
        rate_per_second=1000.0,
        burst=1000,
    )
    count = 0

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url, kwargs
        nonlocal count
        count += 1
        return CallbackResult(
            status=400,
            payload={"error": {"code": 100, "message": "other"}},
        )

    caplog.set_level(logging.ERROR, logger="seerflow")
    with aioresponses() as mock:
        mock.post(
            "https://graph.facebook.com/v18.0/PID/messages",
            callback=_capture,
            repeat=True,
        )
        async with aiohttp.ClientSession() as session:
            await target.deliver(make_alert(), session=session)
            await target.deliver(make_alert(), session=session)
        assert count == 2

    code_lines = [rec.getMessage() for rec in caplog.records if "code=100" in rec.getMessage()]
    assert len(code_lines) == 2
    assert target._circuit.open_until == 0.0


@pytest.mark.unit
async def test_whatsapp_empty_digest_no_network_io() -> None:
    target = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+1",),
    )
    with aioresponses() as mock:
        async with aiohttp.ClientSession() as session:
            await target.deliver_digest([], session=session)
        assert not mock.requests


@pytest.mark.unit
async def test_whatsapp_digest_sends_one_template_with_top_alert() -> None:
    target = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+1",),
        rate_per_second=1000.0,
        burst=1000,
    )
    captured: list[dict[str, Any]] = []

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url
        captured.append(kwargs.get("json") or {})
        return CallbackResult(status=200, payload={"messages": []})

    with aioresponses() as mock:
        mock.post(
            "https://graph.facebook.com/v18.0/PID/messages",
            callback=_capture,
        )
        async with aiohttp.ClientSession() as session:
            alerts = [
                make_alert(rule_name="warn", severity_id=SeverityLevel.WARNING),
                make_alert(rule_name="top", severity_id=SeverityLevel.CRITICAL),
                make_alert(rule_name="err", severity_id=SeverityLevel.ERROR),
            ]
            await target.deliver_digest(alerts, session=session)

    assert len(captured) == 1
    params = captured[0]["template"]["components"][0]["parameters"]
    texts = [p["text"] for p in params]
    assert "top" in texts
    assert "CRITICAL" in texts


@pytest.mark.unit
async def test_whatsapp_retries_503_then_succeeds() -> None:
    """Transient 5xx must be retried; the eventual 200 must produce a single delivery."""
    target = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+15559876543",),
        rate_per_second=1000.0,
        burst=1000,
    )
    call_count = 0

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url, kwargs
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CallbackResult(status=503, payload={})
        return CallbackResult(status=200, payload={"messages": []})

    with aioresponses() as mock:
        mock.post(
            "https://graph.facebook.com/v18.0/PID/messages",
            callback=_capture,
            repeat=True,
        )
        async with aiohttp.ClientSession() as session:
            await _deliver_with_zero_delay(target, session)

    assert call_count == 2


@pytest.mark.unit
async def test_whatsapp_5xx_with_meta_code_does_not_double_log_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 5xx response that happens to carry a Meta ``code`` field must NOT be
    escalated to ERROR by the inspector. ``post_with_retry`` already logs
    WARNING per attempt and ERROR on exhaustion; double-logging at ERROR per
    attempt would trigger operator alert fatigue for transient outages."""

    target = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+15559876543",),
        rate_per_second=1000.0,
        burst=1000,
    )

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url, kwargs
        return CallbackResult(status=503, payload={"error": {"code": 4, "message": "rate limit"}})

    caplog.set_level(logging.ERROR, logger="seerflow")
    with aioresponses() as mock:
        mock.post(
            "https://graph.facebook.com/v18.0/PID/messages",
            callback=_capture,
            repeat=True,
        )
        async with aiohttp.ClientSession() as session:
            await _deliver_with_zero_delay(target, session)

    inspector_lines = [
        rec.getMessage() for rec in caplog.records if "delivery failed" in rec.getMessage()
    ]
    assert inspector_lines == []


@pytest.mark.unit
async def test_whatsapp_three_5xx_exhausts_retries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Three 503s in a row exhaust the retry envelope and emit one error log."""

    target = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+15559876543",),
        rate_per_second=1000.0,
        burst=1000,
    )
    call_count = 0

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url, kwargs
        nonlocal call_count
        call_count += 1
        return CallbackResult(status=503, payload={})

    caplog.set_level(logging.ERROR, logger="seerflow")
    with aioresponses() as mock:
        mock.post(
            "https://graph.facebook.com/v18.0/PID/messages",
            callback=_capture,
            repeat=True,
        )
        async with aiohttp.ClientSession() as session:
            await _deliver_with_zero_delay(target, session)

    assert call_count == 3
    error_lines = [
        rec
        for rec in caplog.records
        if rec.levelno >= logging.ERROR and "exhausted" in rec.getMessage()
    ]
    assert len(error_lines) == 1


@pytest.mark.unit
async def test_whatsapp_503_then_131026_opens_circuit_mid_retry() -> None:
    """A 503 followed by a 131026 must open the circuit and stop retrying."""
    now = [0.0]

    def fake_mono() -> float:
        return now[0]

    target = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+15559876543",),
        rate_per_second=1000.0,
        burst=1000,
        _monotonic=fake_mono,
    )
    call_count = 0

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url, kwargs
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CallbackResult(status=503, payload={})
        return CallbackResult(
            status=400,
            payload={"error": {"code": 131026, "message": "template not found"}},
        )

    with aioresponses() as mock:
        mock.post(
            "https://graph.facebook.com/v18.0/PID/messages",
            callback=_capture,
            repeat=True,
        )
        async with aiohttp.ClientSession() as session:
            await _deliver_with_zero_delay(target, session)

    assert call_count == 2
    assert target._circuit.open_until > 0.0


@pytest.mark.unit
async def test_whatsapp_non_dict_error_field_is_treated_as_no_code() -> None:
    """A compromised upstream returning ``error: [list]`` (not a dict) must not
    raise AttributeError inside the inspector, which would convert a terminal
    4xx into a retried failure via post_with_retry's broad except."""
    target = WhatsAppTarget(
        name="w",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+15559876543",),
        rate_per_second=1000.0,
        burst=1000,
    )
    call_count = 0

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url, kwargs
        nonlocal call_count
        call_count += 1
        return CallbackResult(status=400, payload={"error": [1, 2, 3]})

    with aioresponses() as mock:
        mock.post(
            "https://graph.facebook.com/v18.0/PID/messages",
            callback=_capture,
            repeat=True,
        )
        async with aiohttp.ClientSession() as session:
            await _deliver_with_zero_delay(target, session)

    assert call_count == 1
    assert target._circuit.open_until == 0.0


@pytest.mark.unit
async def test_whatsapp_transport_error_does_not_leak_bearer_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Defence in depth: any aiohttp transport error message that happens to
    echo the request headers must not leak the bearer access token. The shared
    ``_scrub_secrets`` helper covers this via the ``Bearer <token>`` pattern.
    """
    from seerflow.alerting._http import _scrub_secrets

    leaky_message = (
        "Cannot connect to https://graph.facebook.com — Authorization: Bearer secret-wa-token"
    )
    caplog.set_level(logging.WARNING, logger="seerflow")

    scrubbed = _scrub_secrets(leaky_message)

    assert "secret-wa-token" not in scrubbed
    assert "Bearer <redacted>" in scrubbed
