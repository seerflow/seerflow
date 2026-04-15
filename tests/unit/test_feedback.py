"""Tests for TP/FP feedback processing — storage update + DSPOT adjustment."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def _make_alert(
    *,
    alert_id: str = "",
    alert_type: str = "ml",
    rule_name: str = "hst-anomaly",
    entity_uuid: str = "",
    dedup_key: str = "",
) -> Alert:
    eid = entity_uuid or str(uuid.uuid4())
    return Alert(
        alert_id=alert_id or str(uuid.uuid4()),
        alert_type=alert_type,
        timestamp_ns=1_710_000_000_000_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name=rule_name,
        description="test alert",
        entity_uuid=eid,
        entity_value="192.168.1.1",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        dedup_key=dedup_key or str(uuid.uuid4()),
    )


class TestDeriveSourceKey:
    def test_hst_dedup_key_extracts_source_type(self) -> None:
        """HST dedup_key 'hst:42:syslog:entity' yields 'syslog'."""
        from seerflow.alerting.feedback import _derive_source_key

        alert = _make_alert(dedup_key="hst:42:syslog:entity-abc")
        assert _derive_source_key(alert) == "syslog"

    def test_non_hst_dedup_key_falls_back_to_alert_type(self) -> None:
        """Non-HST dedup_key falls back to alert_type."""
        from seerflow.alerting.feedback import _derive_source_key

        alert = _make_alert(alert_type="sigma", dedup_key="sigma:rule1:entity")
        assert _derive_source_key(alert) == "sigma"

    def test_risk_dedup_key_falls_back(self) -> None:
        """Risk dedup_key 'risk:entity-uuid' falls back to alert_type."""
        from seerflow.alerting.feedback import _derive_source_key

        alert = _make_alert(alert_type="ml", dedup_key="risk:entity-abc")
        assert _derive_source_key(alert) == "ml"


class TestProcessFeedback:
    async def test_fp_updates_storage(self) -> None:
        """FP feedback writes feedback to storage via update_feedback."""
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert()
        storage = AsyncMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        result = await process_feedback(
            alert_id=alert.alert_id,
            feedback="fp",
            storage=storage,
        )

        storage.update_feedback.assert_awaited_once_with(alert.alert_id, "fp", "")
        assert "fp" in result.lower() or "FP" in result

    async def test_tp_updates_storage(self) -> None:
        """TP feedback writes feedback to storage via update_feedback."""
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert()
        storage = AsyncMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        result = await process_feedback(
            alert_id=alert.alert_id,
            feedback="tp",
            storage=storage,
        )

        storage.update_feedback.assert_awaited_once_with(alert.alert_id, "tp", "")
        assert "tp" in result.lower() or "TP" in result

    async def test_fp_adjusts_dspot_threshold(self) -> None:
        """FP feedback calls adjust_upper_threshold on ensemble with source_type from dedup_key."""
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert(dedup_key="hst:42:syslog:entity-abc")
        storage = AsyncMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        ensemble = MagicMock()
        ensemble.adjust_upper_threshold = MagicMock(return_value=True)

        result = await process_feedback(
            alert_id=alert.alert_id,
            feedback="fp",
            storage=storage,
            ensemble=ensemble,
        )

        ensemble.adjust_upper_threshold.assert_called_once_with("syslog", 1.05)
        assert "threshold" in result.lower() or "DSPOT" in result

    async def test_tp_does_not_adjust_threshold(self) -> None:
        """TP feedback does NOT adjust DSPOT threshold."""
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert()
        storage = AsyncMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        ensemble = MagicMock()
        ensemble.adjust_upper_threshold = MagicMock(return_value=True)

        await process_feedback(
            alert_id=alert.alert_id,
            feedback="tp",
            storage=storage,
            ensemble=ensemble,
        )

        ensemble.adjust_upper_threshold.assert_not_called()

    async def test_nonexistent_alert_raises(self) -> None:
        """Feedback for a missing alert raises ValueError."""
        from seerflow.alerting.feedback import process_feedback

        storage = AsyncMock()
        storage.get_alert_by_id = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await process_feedback(
                alert_id="nonexistent-id",
                feedback="fp",
                storage=storage,
            )

    async def test_fp_without_ensemble_skips_threshold(self) -> None:
        """FP with ensemble=None skips threshold adjustment."""
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert()
        storage = AsyncMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        result = await process_feedback(
            alert_id=alert.alert_id,
            feedback="fp",
            storage=storage,
            ensemble=None,
        )

        assert "threshold" not in result.lower()

    async def test_fp_ensemble_not_calibrated(self) -> None:
        """FP when DSPOT is not calibrated (returns False) — no threshold msg."""
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert()
        storage = AsyncMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        ensemble = MagicMock()
        ensemble.adjust_upper_threshold = MagicMock(return_value=False)

        result = await process_feedback(
            alert_id=alert.alert_id,
            feedback="fp",
            storage=storage,
            ensemble=ensemble,
        )

        ensemble.adjust_upper_threshold.assert_called_once()
        assert "threshold" not in result.lower()

    async def test_fp_with_pagerduty_resolves_incident(self) -> None:
        """FP with pagerduty_routing_key sends resolve event."""
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert(
            alert_type="ml",
            rule_name="hst-anomaly",
        )
        storage = AsyncMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        with patch(
            "seerflow.alerting.feedback._resolve_pagerduty", new_callable=AsyncMock
        ) as mock_resolve:
            result = await process_feedback(
                alert_id=alert.alert_id,
                feedback="fp",
                storage=storage,
                pagerduty_routing_key="test-routing-key",
            )

        expected_dedup = f"{alert.alert_type}:{alert.rule_name}:{alert.entity_uuid}"
        mock_resolve.assert_awaited_once_with(expected_dedup, "test-routing-key")
        assert "pagerduty" in result.lower()

    async def test_tp_does_not_resolve_pagerduty(self) -> None:
        """TP feedback does NOT send PagerDuty resolve."""
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert()
        storage = AsyncMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        with patch(
            "seerflow.alerting.feedback._resolve_pagerduty", new_callable=AsyncMock
        ) as mock_resolve:
            await process_feedback(
                alert_id=alert.alert_id,
                feedback="tp",
                storage=storage,
                pagerduty_routing_key="test-routing-key",
            )

        mock_resolve.assert_not_awaited()

    async def test_fp_no_pagerduty_key_skips_resolve(self) -> None:
        """FP with empty pagerduty_routing_key skips resolve."""
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert()
        storage = AsyncMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        with patch(
            "seerflow.alerting.feedback._resolve_pagerduty", new_callable=AsyncMock
        ) as mock_resolve:
            result = await process_feedback(
                alert_id=alert.alert_id,
                feedback="fp",
                storage=storage,
                pagerduty_routing_key="",
            )

        mock_resolve.assert_not_awaited()
        assert "pagerduty" not in result.lower()


class TestResolvePagerduty:
    async def test_resolve_sends_correct_payload(self) -> None:
        """_resolve_pagerduty POSTs correct payload to Events API v2."""
        from seerflow.alerting.feedback import _resolve_pagerduty

        mock_response = AsyncMock()
        mock_response.status = 202
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await _resolve_pagerduty("test-dedup-key", "test-routing-key")

        mock_session.post.assert_called_once()
        call_kwargs = mock_session.post.call_args
        assert call_kwargs[0][0] == "https://events.pagerduty.com/v2/enqueue"
        payload = call_kwargs[1]["json"]
        assert payload["routing_key"] == "test-routing-key"
        assert payload["event_action"] == "resolve"
        assert payload["dedup_key"] == "test-dedup-key"

    async def test_resolve_logs_warning_on_http_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_resolve_pagerduty logs warning on HTTP 4xx/5xx."""
        import logging

        from seerflow.alerting.feedback import _resolve_pagerduty

        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            caplog.at_level(logging.WARNING, logger="seerflow"),
        ):
            await _resolve_pagerduty("key", "rk")

        assert any("500" in r.message for r in caplog.records)

    async def test_resolve_logs_warning_on_exception(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_resolve_pagerduty logs warning on network failure."""
        import logging

        from seerflow.alerting.feedback import _resolve_pagerduty

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=ConnectionError("network down"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            caplog.at_level(logging.WARNING, logger="seerflow"),
        ):
            await _resolve_pagerduty("key", "rk")

        assert any("failed" in r.message.lower() for r in caplog.records)


class TestUpdateFeedbackNote:
    async def test_update_feedback_forwards_note(self) -> None:
        """process_feedback must forward note through storage.update_feedback."""
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert()
        storage = MagicMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        await process_feedback(
            alert_id=alert.alert_id,
            feedback="tp",
            storage=storage,
            note="manual triage: matches known vuln scanner",
        )

        storage.update_feedback.assert_awaited_once_with(
            alert.alert_id, "tp", "manual triage: matches known vuln scanner"
        )

    async def test_update_feedback_defaults_note_to_empty(self) -> None:
        from seerflow.alerting.feedback import process_feedback

        alert = _make_alert()
        storage = MagicMock()
        storage.get_alert_by_id = AsyncMock(return_value=alert)
        storage.update_feedback = AsyncMock()

        await process_feedback(alert_id=alert.alert_id, feedback="tp", storage=storage)

        storage.update_feedback.assert_awaited_once_with(alert.alert_id, "tp", "")
