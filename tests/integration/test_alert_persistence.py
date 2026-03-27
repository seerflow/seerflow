"""Integration tests for alert persistence — handler → storage round-trip."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from seerflow.detection.ensemble import DetectionResult
from seerflow.models.event import SeverityLevel
from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from pathlib import Path


class TestAlertPersistenceIntegration:
    """Integration: handler → anomaly → alert → storage → query round-trip."""

    async def test_anomaly_creates_queryable_alert(self, tmp_path: Path) -> None:
        """Anomaly detection → alert persisted → queryable via query_alerts."""
        from seerflow.pipeline.handler import _make_handler
        from seerflow.config import SeerflowConfig, StorageConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models.query import AlertQuery
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        handler = _make_handler(ensemble, storage)

        anomaly_result = DetectionResult(
            score=0.92,
            upper_threshold=0.65,
            lower_threshold=0.10,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="syslog",
        )

        with patch.object(type(ensemble), "process_event", return_value=anomaly_result):
            event = RawEvent(
                data=b"segfault in module xyz",
                source_type="syslog",
                source_id="test",
                received_ns=1_700_000_000_000_000_000,
                metadata={"seerflow_severity": SeverityLevel.CRITICAL.value},
            )
            await handler(event)

        # Flush event buffer
        assert storage._write_buffer is not None
        await storage._write_buffer.flush()

        result = await storage.query_alerts(AlertQuery(limit=10))
        assert len(result.items) == 1

        alert = result.items[0]
        assert alert.alert_type == "ml"
        assert alert.rule_name == "hst-anomaly"
        assert alert.risk_score == 0.92
        assert alert.severity_id == SeverityLevel.CRITICAL
        assert "0.920" in alert.description

        await storage.close()

    async def test_dedup_increments_count(self, tmp_path: Path) -> None:
        """Two anomalies with same template+source → dedup_count >= 2."""
        from seerflow.pipeline.handler import _make_handler
        from seerflow.config import SeerflowConfig, StorageConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models.query import AlertQuery
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        handler = _make_handler(ensemble, storage)

        anomaly_result = DetectionResult(
            score=0.88,
            upper_threshold=0.65,
            lower_threshold=0.10,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="syslog",
        )

        with patch.object(type(ensemble), "process_event", return_value=anomaly_result):
            for i in range(3):
                event = RawEvent(
                    data=f"repeated anomaly event {i}".encode(),
                    source_type="syslog",
                    source_id="test",
                    received_ns=1_700_000_000_000_000_000 + i,
                    metadata={},
                )
                await handler(event)

        assert storage._write_buffer is not None
        await storage._write_buffer.flush()

        result = await storage.query_alerts(AlertQuery(limit=10))
        # All 3 should dedup into 1 alert (same template_id + source_type)
        assert len(result.items) == 1
        assert result.items[0].dedup_count == 3

        await storage.close()
