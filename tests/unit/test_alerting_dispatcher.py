"""Tests for AlertDispatcher: async queue, consumer, retry, severity filtering."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from seerflow.alerting.dispatcher import AlertDispatcher, WebhookTarget
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_alert(
    *,
    alert_id: str = "550e8400-e29b-41d4-a716-446655440000",
    severity_id: SeverityLevel = SeverityLevel.ERROR,
    rule_name: str = "test-rule",
    description: str = "Test alert",
    entity_value: str = "192.168.1.1",
) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=severity_id,
        rule_name=rule_name,
        description=description,
        entity_uuid="entity-uuid-001",
        entity_value=entity_value,
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.75,
        dedup_key="test:dedup",
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


async def _run_and_cancel(dispatcher: AlertDispatcher, delay: float = 0.05) -> None:
    """Start dispatcher.run() as a task, wait briefly, then cancel it."""
    task = asyncio.create_task(dispatcher.run())
    await asyncio.sleep(delay)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@contextmanager
def caplog_handler(logger_name: str):
    """Capture log records emitted on `logger_name` during the block."""
    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger(logger_name)
    handler = _ListHandler(level=logging.DEBUG)
    logger.addHandler(handler)
    prior_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prior_level)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAlertDispatcher:
    @pytest.mark.asyncio
    async def test_formatter_error_logs_and_continues(self) -> None:
        """If the formatter raises, the dispatcher logs and skips that target."""
        session = _mock_session(status=200)
        target = WebhookTarget(
            name="json",
            url="https://hooks.example.com/json",
            format="json",
            min_severity=0,
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        alert = _make_alert()

        with patch("seerflow.alerting.dispatcher._format", side_effect=ValueError("boom")):
            dispatcher.enqueue(alert)
            await dispatcher.stop()
            await _run_and_cancel(dispatcher)

        session.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_enqueue_and_dispatch(self) -> None:
        """Alert enqueued is dispatched to the configured target URL."""
        session = _mock_session(status=200)
        target = WebhookTarget(
            name="json", url="https://hooks.example.com/json", format="json", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        dispatcher.enqueue(_make_alert())
        await dispatcher.stop()
        await _run_and_cancel(dispatcher)

        session.post.assert_called_once()
        assert session.post.call_args[0][0] == "https://hooks.example.com/json"

    @pytest.mark.asyncio
    async def test_dispatch_sends_correct_payload(self) -> None:
        """Payload POSTed matches format_json output for the alert."""
        from seerflow.alerting.formatters import format_json

        session = _mock_session(status=200)
        target = WebhookTarget(
            name="json", url="https://hooks.example.com/json", format="json", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        alert = _make_alert()
        expected_payload = format_json(alert)

        dispatcher.enqueue(alert)
        await dispatcher.stop()
        await _run_and_cancel(dispatcher)

        assert session.post.call_args[1]["json"] == expected_payload

    @pytest.mark.asyncio
    async def test_severity_filter(self) -> None:
        """Alert below min_severity is not dispatched."""
        session = _mock_session(status=200)
        target = WebhookTarget(
            name="json",
            url="https://hooks.example.com/json",
            format="json",
            min_severity=int(SeverityLevel.CRITICAL),
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        # WARNING is below CRITICAL — should be filtered out
        dispatcher.enqueue(_make_alert(severity_id=SeverityLevel.WARNING))
        await dispatcher.stop()
        await _run_and_cancel(dispatcher)

        session.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_severity_filter_allows_equal_severity(self) -> None:
        """Alert with severity == min_severity is dispatched."""
        session = _mock_session(status=200)
        target = WebhookTarget(
            name="json",
            url="https://hooks.example.com/json",
            format="json",
            min_severity=int(SeverityLevel.ERROR),
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        dispatcher.enqueue(_make_alert(severity_id=SeverityLevel.ERROR))
        await dispatcher.stop()
        await _run_and_cancel(dispatcher)

        session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_queue_full_logs_warning(self) -> None:
        """When queue is full, enqueue logs a warning and drops the alert."""
        session = _mock_session(status=200)
        target = WebhookTarget(
            name="json", url="https://hooks.example.com/json", format="json", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session, queue_maxsize=2)

        # Fill the queue without starting the consumer
        alert = _make_alert()
        dispatcher.enqueue(alert)
        dispatcher.enqueue(alert)

        # Third enqueue should hit the full queue and log a warning
        with patch("seerflow.alerting.dispatcher._log") as mock_log:
            dispatcher.enqueue(alert)
            mock_log.warning.assert_called_once()
            warning_msg = mock_log.warning.call_args[0][0]
            assert "queue full" in warning_msg.lower() or "dropping" in warning_msg.lower()

    @pytest.mark.asyncio
    async def test_retry_on_failure(self) -> None:
        """Failed POST (HTTP 500) is retried up to 3 times; succeeds on 3rd."""
        call_count = 0

        async def fake_aenter(_self: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return MagicMock(status=500)
            return MagicMock(status=200)

        resp_cm = MagicMock()
        resp_cm.__aenter__ = fake_aenter
        resp_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        target = WebhookTarget(
            name="json", url="https://hooks.example.com/json", format="json", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        dispatcher.enqueue(_make_alert())
        await dispatcher.stop()

        # Patch asyncio in dispatcher module so sleep is a no-op
        sleep_mock = AsyncMock(return_value=None)
        with patch("seerflow.alerting.dispatcher.asyncio") as mock_asyncio:
            mock_asyncio.Queue = asyncio.Queue
            mock_asyncio.QueueFull = asyncio.QueueFull
            mock_asyncio.wait_for = asyncio.wait_for
            mock_asyncio.sleep = sleep_mock
            await asyncio.wait_for(dispatcher.run(), timeout=5.0)

        # 2 x 500 failures + 1 x 200 success
        assert session.post.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_exception(self) -> None:
        """POST raising an exception is retried; succeeds on 3rd attempt."""
        call_count = 0

        async def fake_aenter(_self: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("connection refused")
            return MagicMock(status=200)

        resp_cm = MagicMock()
        resp_cm.__aenter__ = fake_aenter
        resp_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        target = WebhookTarget(
            name="json", url="https://hooks.example.com/json", format="json", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        dispatcher.enqueue(_make_alert())
        await dispatcher.stop()

        sleep_mock = AsyncMock(return_value=None)
        with patch("seerflow.alerting.dispatcher.asyncio") as mock_asyncio:
            mock_asyncio.Queue = asyncio.Queue
            mock_asyncio.QueueFull = asyncio.QueueFull
            mock_asyncio.wait_for = asyncio.wait_for
            mock_asyncio.sleep = sleep_mock
            await asyncio.wait_for(dispatcher.run(), timeout=5.0)

        assert session.post.call_count == 3

    @pytest.mark.asyncio
    async def test_dispatch_exhausts_retries_on_persistent_failure(self) -> None:
        """After 3 failed attempts (all 500), dispatcher stops retrying without crash."""
        resp_cm = MagicMock()
        resp_cm.__aenter__ = AsyncMock(return_value=MagicMock(status=500))
        resp_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        target = WebhookTarget(
            name="json", url="https://hooks.example.com/json", format="json", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        dispatcher.enqueue(_make_alert())
        await dispatcher.stop()

        sleep_mock = AsyncMock(return_value=None)
        with patch("seerflow.alerting.dispatcher.asyncio") as mock_asyncio:
            mock_asyncio.Queue = asyncio.Queue
            mock_asyncio.QueueFull = asyncio.QueueFull
            mock_asyncio.wait_for = asyncio.wait_for
            mock_asyncio.sleep = sleep_mock
            await asyncio.wait_for(dispatcher.run(), timeout=5.0)

        assert session.post.call_count == 3

    @pytest.mark.asyncio
    async def test_multiple_targets(self) -> None:
        """Alert is dispatched to all configured targets."""
        call_urls: list[str] = []
        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=MagicMock(status=200))
        resp_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()

        def track_post(url: str, **kwargs: object) -> AsyncMock:
            call_urls.append(url)
            return resp_cm

        session.post = MagicMock(side_effect=track_post)

        target1 = WebhookTarget(
            name="t1", url="https://hooks1.example.com/json", format="json", min_severity=0
        )
        target2 = WebhookTarget(
            name="t2", url="https://hooks2.example.com/slack", format="slack", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target1, target2), session=session)

        dispatcher.enqueue(_make_alert())
        await dispatcher.stop()
        await _run_and_cancel(dispatcher)

        assert "https://hooks1.example.com/json" in call_urls
        assert "https://hooks2.example.com/slack" in call_urls

    @pytest.mark.asyncio
    async def test_stop_drains_queue_before_exit(self) -> None:
        """After stop(), run() drains remaining queue items before returning."""
        dispatched: list[str] = []
        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=MagicMock(status=200))
        resp_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()

        def track_post(url: str, **kwargs: object) -> AsyncMock:
            payload = kwargs.get("json", {})
            alert_id = payload.get("alert_id", "")
            dispatched.append(alert_id)
            return resp_cm

        session.post = MagicMock(side_effect=track_post)

        target = WebhookTarget(
            name="json", url="https://hooks.example.com/json", format="json", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        for i in range(3):
            dispatcher.enqueue(_make_alert(alert_id=f"alert-{i:03d}"))
        await dispatcher.stop()

        # run() must drain all 3 before returning
        await asyncio.wait_for(dispatcher.run(), timeout=5.0)

        assert len(dispatched) == 3

    @pytest.mark.asyncio
    async def test_slack_format_dispatched(self) -> None:
        """Slack format target receives Slack Block Kit payload."""
        from seerflow.alerting.formatters import format_slack

        captured_payload: list[dict] = []  # type: ignore[type-arg]
        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=MagicMock(status=200))
        resp_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()

        def capture_post(url: str, **kwargs: object) -> AsyncMock:
            captured_payload.append(kwargs.get("json", {}))  # type: ignore[arg-type]
            return resp_cm

        session.post = MagicMock(side_effect=capture_post)

        target = WebhookTarget(
            name="slack", url="https://hooks.example.com/slack", format="slack", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        alert = _make_alert()
        expected = format_slack(alert)

        dispatcher.enqueue(alert)
        await dispatcher.stop()
        await _run_and_cancel(dispatcher)

        assert captured_payload == [expected]

    @pytest.mark.asyncio
    async def test_teams_format_dispatched(self) -> None:
        """Teams format target receives Teams Adaptive Card payload."""
        from seerflow.alerting.formatters import format_teams

        captured_payload: list[dict] = []  # type: ignore[type-arg]
        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=MagicMock(status=200))
        resp_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()

        def capture_post(url: str, **kwargs: object) -> AsyncMock:
            captured_payload.append(kwargs.get("json", {}))  # type: ignore[arg-type]
            return resp_cm

        session.post = MagicMock(side_effect=capture_post)

        target = WebhookTarget(
            name="teams", url="https://hooks.example.com/teams", format="teams", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        alert = _make_alert()
        expected = format_teams(alert)

        dispatcher.enqueue(alert)
        await dispatcher.stop()
        await _run_and_cancel(dispatcher)

        assert captured_payload == [expected]


class TestDispatcherDashboardUrl:
    @pytest.mark.asyncio
    async def test_dashboard_url_passed_to_formatter(self) -> None:
        """Dashboard URL is forwarded from dispatcher to the formatter."""
        session = _mock_session(status=200)
        target = WebhookTarget(
            name="slack", url="https://hooks.example.com/slack", format="slack", min_severity=0
        )
        dispatcher = AlertDispatcher(
            targets=(target,),
            session=session,
            dashboard_url="https://seerflow.example.com",
        )
        alert = _make_alert()
        dispatcher.enqueue(alert)
        await dispatcher.stop()
        await _run_and_cancel(dispatcher)
        posted_payload = session.post.call_args[1]["json"]
        actions = [b for b in posted_payload["blocks"] if b.get("type") == "actions"]
        assert len(actions) == 1
        assert actions[0]["elements"][0]["url"] == "https://seerflow.example.com"

    @pytest.mark.asyncio
    async def test_no_dashboard_url_no_actions_block(self) -> None:
        """Without dashboard_url, Slack payload has no actions block."""
        session = _mock_session(status=200)
        target = WebhookTarget(
            name="slack", url="https://hooks.example.com/slack", format="slack", min_severity=0
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)
        alert = _make_alert()
        dispatcher.enqueue(alert)
        await dispatcher.stop()
        await _run_and_cancel(dispatcher)
        posted_payload = session.post.call_args[1]["json"]
        actions = [b for b in posted_payload["blocks"] if b.get("type") == "actions"]
        assert len(actions) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatcher_preserves_legacy_fanout_when_router_absent() -> None:
    """No router ⇒ today's per-target min_severity fan-out runs unchanged."""
    from tests.unit.alert_factory import make_alert

    session = _mock_session(status=200)
    t_low = WebhookTarget(name="low", url="https://a/x", format="json", min_severity=0)
    t_high = WebhookTarget(name="high", url="https://b/x", format="json", min_severity=5)

    d = AlertDispatcher(targets=(t_low, t_high), session=session)
    d.enqueue(make_alert(severity_id=SeverityLevel.WARNING))
    await d.stop()
    await asyncio.wait_for(d.run(), timeout=5.0)

    # Only t_low receives the WARNING alert (sev=3 < 5 for t_high)
    assert session.post.call_count == 1
    assert session.post.call_args[0][0] == "https://a/x"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatcher_delegates_when_router_present() -> None:
    """Router wired ⇒ dispatcher calls router.route instead of per-target fan-out."""
    from tests.unit.alert_factory import make_alert

    session = _mock_session(status=200)
    target = WebhookTarget(name="t1", url="https://a/x", format="json")
    fake_router = AsyncMock()

    d = AlertDispatcher(targets=(target,), session=session, router=fake_router)
    alert = make_alert()
    d.enqueue(alert)
    await d.stop()
    await asyncio.wait_for(d.run(), timeout=5.0)

    fake_router.route.assert_awaited_once_with(alert)
    session.post.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatcher_run_stops_router_after_queue_drains() -> None:
    """run() must await router.stop() after draining so digest buffers flush."""
    session = _mock_session(status=200)
    target = WebhookTarget(name="t1", url="https://a/x", format="json")
    fake_router = AsyncMock()

    d = AlertDispatcher(targets=(target,), session=session, router=fake_router)
    await d.stop()  # signal only; router is still live so run() can route queued alerts
    await asyncio.wait_for(d.run(), timeout=5.0)

    fake_router.stop.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_survives_programmer_error_in_router_route() -> None:
    """AC-3(b): a programmer error inside router.route must not kill the consumer.

    `AlertDispatcher._dispatch` guards the legacy per-target fan-out
    (`_format` / `_post_with_retry`) but not the earlier
    `await self._router.route(alert)` call. If `router.route` raises an
    unexpected exception (e.g. TypeError from a refactor bug in rule
    matching or quiet-hours logic), the consumer task dies silently.
    """
    from tests.unit.alert_factory import make_alert

    session = _mock_session(status=200)
    target = WebhookTarget(name="t1", url="https://a/x", format="json")

    fake_router = AsyncMock()
    fake_router.route.side_effect = [TypeError("boom"), None]
    # Ensure router.stop() (called after queue drains) is awaitable and side-effect-free.
    fake_router.stop = AsyncMock(return_value=None)

    d = AlertDispatcher(targets=(target,), session=session, router=fake_router)
    d.enqueue(make_alert())
    d.enqueue(make_alert())
    await d.stop()

    with caplog_handler("seerflow") as records:
        await asyncio.wait_for(d.run(), timeout=5.0)

    assert fake_router.route.await_count == 2, (
        "second alert was never routed — consumer likely died on first TypeError"
    )
    matching = [
        r
        for r in records
        if "AlertDispatcher: unexpected error in router.route" in r.getMessage()
    ]
    assert len(matching) == 1, (
        f"expected exactly one guard log line, got {len(matching)}: "
        f"{[r.getMessage() for r in records]}"
    )
    # AC-4: no alert content in the log message.
    msg = matching[0].getMessage()
    assert "alert_id" not in msg
    assert "entity_value" not in msg
    session.post.assert_not_called()


class TestResponseBodyLogging:
    @pytest.mark.asyncio
    async def test_4xx_reads_response_body(self) -> None:
        """On 4xx, dispatcher reads response body via text() for logging."""
        resp_mock = MagicMock(status=400)
        resp_mock.text = AsyncMock(return_value="Bad Request: missing field")

        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
        resp_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        target = WebhookTarget(
            name="json",
            url="https://hooks.example.com/json",
            format="json",
            min_severity=0,
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        dispatcher.enqueue(_make_alert())
        await dispatcher.stop()
        await asyncio.wait_for(dispatcher.run(), timeout=5.0)

        resp_mock.text.assert_called_once()

    @pytest.mark.asyncio
    async def test_5xx_reads_response_body(self) -> None:
        """On 5xx, dispatcher reads response body via text() for logging."""
        resp_mock = MagicMock(status=500)
        resp_mock.text = AsyncMock(return_value="Internal Server Error")

        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
        resp_cm.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        target = WebhookTarget(
            name="json",
            url="https://hooks.example.com/json",
            format="json",
            min_severity=0,
        )
        dispatcher = AlertDispatcher(targets=(target,), session=session)

        dispatcher.enqueue(_make_alert())
        await dispatcher.stop()

        sleep_mock = AsyncMock(return_value=None)
        with patch("seerflow.alerting.dispatcher.asyncio") as mock_asyncio:
            mock_asyncio.Queue = asyncio.Queue
            mock_asyncio.QueueFull = asyncio.QueueFull
            mock_asyncio.wait_for = asyncio.wait_for
            mock_asyncio.sleep = sleep_mock
            await asyncio.wait_for(dispatcher.run(), timeout=5.0)

        assert resp_mock.text.call_count == 3  # 3 retries
