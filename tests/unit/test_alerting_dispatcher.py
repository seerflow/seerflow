"""Tests for AlertDispatcher: async queue, consumer, retry, severity filtering."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
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
    resp_cm = AsyncMock()
    resp_cm.__aenter__ = AsyncMock(return_value=MagicMock(status=status))
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAlertDispatcher:
    @pytest.mark.asyncio
    async def test_enqueue_and_dispatch(self) -> None:
        """Alert enqueued is dispatched to the configured target URL."""
        session = _mock_session(status=200)
        target = WebhookTarget(url="https://hooks.example.com/json", format="json", min_severity=0)
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
        target = WebhookTarget(url="https://hooks.example.com/json", format="json", min_severity=0)
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
        target = WebhookTarget(url="https://hooks.example.com/json", format="json", min_severity=0)
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

        target = WebhookTarget(url="https://hooks.example.com/json", format="json", min_severity=0)
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

        target = WebhookTarget(url="https://hooks.example.com/json", format="json", min_severity=0)
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

        target = WebhookTarget(url="https://hooks.example.com/json", format="json", min_severity=0)
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
            url="https://hooks1.example.com/json", format="json", min_severity=0
        )
        target2 = WebhookTarget(
            url="https://hooks2.example.com/slack", format="slack", min_severity=0
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

        target = WebhookTarget(url="https://hooks.example.com/json", format="json", min_severity=0)
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
            url="https://hooks.example.com/slack", format="slack", min_severity=0
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
            url="https://hooks.example.com/teams", format="teams", min_severity=0
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
        target = WebhookTarget(url="https://hooks.example.com/slack", format="slack", min_severity=0)
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
        target = WebhookTarget(url="https://hooks.example.com/slack", format="slack", min_severity=0)
        dispatcher = AlertDispatcher(targets=(target,), session=session)
        alert = _make_alert()
        dispatcher.enqueue(alert)
        await dispatcher.stop()
        await _run_and_cancel(dispatcher)
        posted_payload = session.post.call_args[1]["json"]
        actions = [b for b in posted_payload["blocks"] if b.get("type") == "actions"]
        assert len(actions) == 0
