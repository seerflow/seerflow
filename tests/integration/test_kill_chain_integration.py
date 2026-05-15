"""Integration test: kill-chain progression alert from multiple alert types."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

if TYPE_CHECKING:
    from pathlib import Path


def _make_alert(
    *,
    entity_uuid: str,
    mitre_tactics: tuple[str, ...],
    timestamp_ns: int = 1_000_000_000_000_000_000,
) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",
        timestamp_ns=timestamp_ns,
        severity_id=SeverityLevel.WARNING,
        rule_name="test",
        description="test",
        entity_uuid=entity_uuid,
        entity_value="10.0.0.1",
        entity_type="ip",
        contributing_events=(),
        mitre_tactics=mitre_tactics,
    )


@pytest.mark.integration
class TestKillChainIntegration:
    async def test_three_tactics_produces_kill_chain_alert(self, tmp_path: Path) -> None:
        """Three alerts with different tactics for same entity -> kill-chain alert."""
        from seerflow.config import KillChainConfig, StorageConfig
        from seerflow.correlation.kill_chain import KillChainTracker
        from seerflow.models.query import AlertQuery
        from seerflow.storage.sqlite import SqliteBackend

        cfg = KillChainConfig(tactic_threshold=3)
        tracker = KillChainTracker(cfg)
        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        try:
            entity = "entity-kill-chain-test"
            alerts = [
                _make_alert(
                    entity_uuid=entity,
                    mitre_tactics=("credential-access",),
                    timestamp_ns=1_000,
                ),
                _make_alert(
                    entity_uuid=entity,
                    mitre_tactics=("lateral-movement",),
                    timestamp_ns=2_000,
                ),
                _make_alert(
                    entity_uuid=entity,
                    mitre_tactics=("execution",),
                    timestamp_ns=3_000,
                ),
            ]
            kc_alerts_all: list[Alert] = []
            for alert in alerts:
                await storage.write_alert(alert, dedup_window_ns=0)
                kc_results = tracker.record_alert(alert)
                kc_alerts_all.extend(kc_results)
                for kc in kc_results:
                    await storage.write_alert(kc, dedup_window_ns=0)

            assert len(kc_alerts_all) == 1
            kc = kc_alerts_all[0]
            assert kc.rule_name == "kill-chain-progression"
            assert len(kc.mitre_tactics) == 3
            assert "credential-access" in kc.mitre_tactics
            assert "lateral-movement" in kc.mitre_tactics
            assert "execution" in kc.mitre_tactics

            result = await storage.query_alerts(AlertQuery(limit=50))
            rule_names = [a.rule_name for a in result.items]
            assert "kill-chain-progression" in rule_names
        finally:
            await storage.close()

    async def test_two_tactics_no_kill_chain_alert(self, tmp_path: Path) -> None:
        """Two tactics for same entity -> no kill-chain alert."""
        from seerflow.config import KillChainConfig
        from seerflow.correlation.kill_chain import KillChainTracker

        tracker = KillChainTracker(KillChainConfig(tactic_threshold=3))
        entity = "entity-two-tactics"
        a1 = _make_alert(entity_uuid=entity, mitre_tactics=("credential-access",))
        a2 = _make_alert(entity_uuid=entity, mitre_tactics=("execution",))
        assert tracker.record_alert(a1) == []
        assert tracker.record_alert(a2) == []
