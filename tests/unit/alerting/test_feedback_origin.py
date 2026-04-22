"""Unit tests for origin propagation through process_feedback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.alerting.feedback import process_feedback


@pytest.mark.asyncio
async def test_process_feedback_threads_origin_to_storage() -> None:
    alert = MagicMock(dedup_key="hst:1:nginx:e-1", alert_type="ml")
    storage = MagicMock()
    storage.get_alert_by_id = AsyncMock(return_value=alert)
    storage.update_feedback = AsyncMock()

    await process_feedback(
        alert_id="a-1",
        feedback="tp",
        storage=storage,
        ensemble=None,
        pagerduty_routing_key="",
        note="",
        origin="cli",
    )

    storage.update_feedback.assert_awaited_once_with("a-1", "tp", "", origin="cli")


@pytest.mark.asyncio
async def test_process_feedback_defaults_origin_to_api() -> None:
    storage = MagicMock()
    storage.get_alert_by_id = AsyncMock(
        return_value=MagicMock(dedup_key="x", alert_type="ml")
    )
    storage.update_feedback = AsyncMock()

    await process_feedback(alert_id="a-1", feedback="tp", storage=storage)
    storage.update_feedback.assert_awaited_once_with("a-1", "tp", "", origin="api")
