"""Unit tests for the shared MITRE-junction backfill helper (S-073)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import msgspec

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.storage._mitre_backfill import decode_alert_for_backfill

if TYPE_CHECKING:
    import pytest


def _build_alert(
    *,
    tactics: tuple[str, ...] = (),
    techniques: tuple[str, ...] = (),
) -> Alert:
    return Alert(
        alert_id="a-1",
        alert_type="ml",
        timestamp_ns=1_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name="r",
        description="d",
        entity_uuid="e",
        entity_value="10.0.0.1",
        entity_type="ip",
        contributing_events=(),
        dedup_key="dk",
        mitre_tactics=tactics,
        mitre_techniques=techniques,
    )


class TestDecodeAlertForBackfill:
    def test_none_blob_returns_none(self) -> None:
        assert decode_alert_for_backfill(None, 1, "dk") is None

    def test_valid_blob_returns_tactics_and_techniques(self) -> None:
        alert = _build_alert(
            tactics=("execution", "persistence"),
            techniques=("T1059", "T1547.001"),
        )
        blob = msgspec.msgpack.encode(alert)
        result = decode_alert_for_backfill(blob, alert.timestamp_ns, alert.dedup_key)
        assert result is not None
        tactics, techniques = result
        assert tactics == ["execution", "persistence"]
        # format_technique uppercases parent technique IDs and preserves
        # sub-technique notation.
        assert "T1059" in techniques
        assert any("T1547" in t for t in techniques)

    def test_empty_tactics_and_techniques(self) -> None:
        alert = _build_alert()
        blob = msgspec.msgpack.encode(alert)
        result = decode_alert_for_backfill(blob, 1, "dk")
        assert result == ([], [])

    def test_corrupt_blob_returns_none_and_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger="seerflow.storage._mitre_backfill")
        result = decode_alert_for_backfill(b"\x00garbage", 1, "dk-bad")
        assert result is None
        assert any("dk-bad" in rec.message for rec in caplog.records)
