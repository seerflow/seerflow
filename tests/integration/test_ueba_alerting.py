"""End-to-end UEBA alerting: handler → UEBAEngine → write_alert → dispatcher."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from seerflow.config import SeerflowConfig, StorageConfig, UEBAConfig
from seerflow.detection.ensemble import DetectionEnsemble, DetectionResult
from seerflow.models.query import AlertQuery
from seerflow.pipeline.handler import make_handler
from seerflow.receivers.base import RawEvent
from seerflow.storage.sqlite import SqliteBackend
from seerflow.ueba.baseline import EntityBaseline, UEBAParams
from seerflow.ueba.engine import UEBAEngine
from seerflow.ueba.store import BaselineStore

if TYPE_CHECKING:
    from pathlib import Path


def _neutral_detection_result() -> DetectionResult:
    """A non-anomaly DetectionResult — avoids the ML alert path firing."""
    return DetectionResult(
        score=0.0,
        upper_threshold=1.0,
        lower_threshold=0.0,
        is_anomaly=False,
        anomaly_direction=None,
        source_type="syslog",
    )


def _seed_warm_baseline(
    store: BaselineStore,
    *,
    entity_uuid: str,
    entity_type: str = "ip",
) -> None:
    """Insert a warmed baseline directly — bypasses the learn loop.

    The baseline is deliberately low-volume (``volume_ema_min=0.0001``)
    and lacks the event's IP/template so every sub-score spikes.
    """
    store._baselines[entity_uuid] = EntityBaseline(
        entity_uuid=entity_uuid,
        entity_type=entity_type,  # type: ignore[arg-type]
        first_seen_ns=0,
        last_seen_ns=10 * 86_400 * 1_000_000_000,
        event_count=100,
        warmup_complete=True,
        hours=tuple(100 if i == 0 else 0 for i in range(24)),
        source_ips=(("10.99.99.99", 0),),  # NOT the event's IP
        volume_ema_min=0.0001,
        volume_ema_hour=0.0001,
        volume_last_ns=10 * 86_400 * 1_000_000_000,
        templates=(("1", 1.0),),
    )


class TestUebaAlertingIntegration:
    """Integration: handler writes a ueba.deviation alert when score crosses."""

    async def test_pipeline_writes_ueba_alert_when_composite_crosses(
        self,
        tmp_path: Path,
    ) -> None:
        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        try:
            config = SeerflowConfig(ueba=UEBAConfig(score_threshold=0.1))
            ensemble = DetectionEnsemble(config.detection)

            params = UEBAParams(
                alpha=0.05,
                source_ip_cap=8,
                template_top_k=8,
                warmup_days=1,
                warmup_min_events=3,
            )
            baseline_store = BaselineStore(params=params, max_entities=100)
            ueba_engine = UEBAEngine(config=config.ueba)

            handler = make_handler(
                ensemble,
                storage,
                baseline_store=baseline_store,
                ueba_engine=ueba_engine,
                alerting_config=config.alerting,
            )

            # Warm baseline for the IP entity that resolve_entities will produce.
            from seerflow.models.entity import generate_ip_id

            entity_uuid = str(generate_ip_id("10.0.0.1"))
            _seed_warm_baseline(baseline_store, entity_uuid=entity_uuid)

            raw = RawEvent(
                data=b"failed ssh login from 10.0.0.1",
                source_type="syslog",
                source_id="test",
                received_ns=12 * 86_400 * 1_000_000_000,
                metadata={},
            )
            with patch.object(
                type(ensemble),
                "process_event",
                return_value=_neutral_detection_result(),
            ):
                await handler(raw)

            await storage.flush()
            result = await storage.query_alerts(AlertQuery(limit=10))
            ueba_alerts = [a for a in result.items if a.alert_type == "ueba"]
            assert len(ueba_alerts) == 1
            alert = ueba_alerts[0]
            assert alert.rule_name == "ueba.deviation"
            assert alert.entity_uuid == entity_uuid
            # Breakdown payload is encoded into the description.
            assert "ueba_breakdown" in alert.description
            assert "composite=" in alert.description
            # last_score cache populated for API exposure.
            snap = ueba_engine.last_score(entity_uuid)
            assert snap is not None
            assert snap.composite >= 0.1
        finally:
            await storage.close()

    async def test_pipeline_dispatches_ueba_alert_once_deduped(
        self,
        tmp_path: Path,
    ) -> None:
        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        try:
            config = SeerflowConfig(ueba=UEBAConfig(score_threshold=0.1))
            ensemble = DetectionEnsemble(config.detection)
            params = UEBAParams(
                alpha=0.05,
                source_ip_cap=8,
                template_top_k=8,
                warmup_days=1,
                warmup_min_events=3,
            )
            baseline_store = BaselineStore(params=params, max_entities=100)
            ueba_engine = UEBAEngine(config=config.ueba)
            mock_dispatcher = MagicMock()
            mock_dispatcher.enqueue = MagicMock()

            handler = make_handler(
                ensemble,
                storage,
                baseline_store=baseline_store,
                ueba_engine=ueba_engine,
                alerting_config=config.alerting,
                alert_dispatcher=mock_dispatcher,
            )

            from seerflow.models.entity import generate_ip_id

            entity_uuid = str(generate_ip_id("10.0.0.1"))
            _seed_warm_baseline(baseline_store, entity_uuid=entity_uuid)

            with patch.object(
                type(ensemble),
                "process_event",
                return_value=_neutral_detection_result(),
            ):
                # Two events, same entity, tight temporal window → dedup.
                for i in range(2):
                    # Re-seed after each event so the learn-path doesn't move
                    # the baseline out from under the scorer.
                    _seed_warm_baseline(baseline_store, entity_uuid=entity_uuid)
                    raw = RawEvent(
                        data=b"failed ssh login from 10.0.0.1",
                        source_type="syslog",
                        source_id="test",
                        received_ns=12 * 86_400 * 1_000_000_000 + i,
                        metadata={},
                    )
                    await handler(raw)

            # enqueue called exactly once — second event dedups.
            ueba_dispatch_calls = [
                c
                for c in mock_dispatcher.enqueue.call_args_list
                if c.args and c.args[0].alert_type == "ueba"
            ]
            assert len(ueba_dispatch_calls) == 1
        finally:
            await storage.close()

    async def test_pipeline_skips_ueba_when_engine_is_none(
        self,
        tmp_path: Path,
    ) -> None:
        """Without a ueba_engine, no UEBA alerts are produced — zero cost."""
        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        try:
            config = SeerflowConfig()
            ensemble = DetectionEnsemble(config.detection)
            params = UEBAParams(
                alpha=0.05,
                source_ip_cap=8,
                template_top_k=8,
                warmup_days=1,
                warmup_min_events=3,
            )
            baseline_store = BaselineStore(params=params, max_entities=100)
            handler = make_handler(
                ensemble,
                storage,
                baseline_store=baseline_store,
                # ueba_engine omitted.
            )

            from seerflow.models.entity import generate_ip_id

            entity_uuid = str(generate_ip_id("10.0.0.1"))
            _seed_warm_baseline(baseline_store, entity_uuid=entity_uuid)

            with patch.object(
                type(ensemble),
                "process_event",
                return_value=_neutral_detection_result(),
            ):
                raw = RawEvent(
                    data=b"failed ssh login from 10.0.0.1",
                    source_type="syslog",
                    source_id="test",
                    received_ns=12 * 86_400 * 1_000_000_000,
                    metadata={},
                )
                await handler(raw)

            await storage.flush()
            result = await storage.query_alerts(AlertQuery(limit=10))
            assert not [a for a in result.items if a.alert_type == "ueba"]
        finally:
            await storage.close()
