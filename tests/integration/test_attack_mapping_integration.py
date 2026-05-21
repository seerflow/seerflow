"""Integration test: ML anomaly alert carries MITRE mapping from AttackMapper."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from seerflow.detection.ensemble import DetectionResult
from seerflow.models.event import SeverityLevel
from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from pathlib import Path


class TestAttackMappingIntegration:
    async def test_ml_alert_gets_mitre_from_mapper(self, tmp_path: Path) -> None:
        from seerflow.config import SeerflowConfig, StorageConfig
        from seerflow.detection.attack_mapping import AttackMapper
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models.query import AlertQuery
        from seerflow.pipeline.handler import make_handler
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mapper = AttackMapper.load_defaults()
        handler = make_handler(ensemble, storage, attack_mapper=mapper)

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
                data=b"error: maximum authentication attempts exceeded for admin from 10.0.0.1",
                source_type="syslog",
                source_id="test",
                received_ns=1_700_000_000_000_000_000,
                metadata={"seerflow_severity": SeverityLevel.CRITICAL.value},
            )
            await handler(event)
        await storage.flush()

        result = await storage.query_alerts(AlertQuery(limit=10))
        assert len(result.items) >= 1
        alert = result.items[0]
        assert alert.alert_type == "ml"
        assert len(alert.mitre_tactics) > 0, "ML alert should have MITRE tactics from mapper"
        has_cred = "credential-access" in alert.mitre_tactics
        has_init = "initial-access" in alert.mitre_tactics
        assert has_cred or has_init
        await storage.close()
