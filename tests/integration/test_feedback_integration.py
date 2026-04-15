"""Integration tests for TP/FP feedback — storage round-trip with real SQLite."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

if TYPE_CHECKING:
    from pathlib import Path


def _make_alert(*, alert_id: str = "", dedup_key: str = "") -> Alert:
    eid = str(uuid.uuid4())
    return Alert(
        alert_id=alert_id or str(uuid.uuid4()),
        alert_type="ml",
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name="hst-anomaly",
        description="test anomaly",
        entity_uuid=eid,
        entity_value="192.168.1.1",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        dedup_key=dedup_key or f"hst:42:syslog:{eid}",
    )


class TestFeedbackIntegration:
    """Integration: process_feedback → SqliteBackend round-trip."""

    async def test_fp_feedback_persists_and_appears_in_stats(self, tmp_path: Path) -> None:
        """FP feedback stored via process_feedback is queryable."""
        from seerflow.alerting.feedback import process_feedback
        from seerflow.config import StorageConfig
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        try:
            alert = _make_alert()
            await storage.write_alert(alert, dedup_window_ns=0)

            result = await process_feedback(
                alert_id=alert.alert_id,
                feedback="fp",
                storage=storage,
            )
            assert "FP" in result

            retrieved = await storage.get_alert_by_id(alert.alert_id)
            assert retrieved is not None
            assert retrieved.feedback == "fp"

            stats = await storage.get_feedback_stats()
            assert stats == {"tp": 0, "fp": 1, "total": 1}
        finally:
            await storage.close()

    async def test_tp_feedback_persists_and_appears_in_stats(self, tmp_path: Path) -> None:
        """TP feedback stored via process_feedback is queryable."""
        from seerflow.alerting.feedback import process_feedback
        from seerflow.config import StorageConfig
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        try:
            alert = _make_alert()
            await storage.write_alert(alert, dedup_window_ns=0)

            result = await process_feedback(
                alert_id=alert.alert_id,
                feedback="tp",
                storage=storage,
            )
            assert "TP" in result

            stats = await storage.get_feedback_stats()
            assert stats == {"tp": 1, "fp": 0, "total": 1}
        finally:
            await storage.close()

    async def test_update_feedback_persists_note(self, tmp_path: Path) -> None:
        """AlertStore.update_feedback stores note in the BLOB and round-trips."""
        from seerflow.config import StorageConfig
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        try:
            alert = _make_alert()
            await storage.write_alert(alert, dedup_window_ns=0)

            await storage.update_feedback(alert.alert_id, "fp", "benign scan")

            reloaded = await storage.get_alert_by_id(alert.alert_id)
            assert reloaded is not None
            assert reloaded.feedback == "fp"
            assert reloaded.feedback_note == "benign scan"
        finally:
            await storage.close()

    async def test_nonexistent_alert_raises_value_error(self, tmp_path: Path) -> None:
        """Feedback on a missing alert raises ValueError."""
        import pytest

        from seerflow.alerting.feedback import process_feedback
        from seerflow.config import StorageConfig
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        try:
            with pytest.raises(ValueError, match="not found"):
                await process_feedback(
                    alert_id="nonexistent-id",
                    feedback="fp",
                    storage=storage,
                )
        finally:
            await storage.close()
