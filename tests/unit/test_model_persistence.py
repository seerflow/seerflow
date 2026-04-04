"""Tests for ML model state persistence — save/load via ModelStore."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from seerflow.models import SeerflowEvent, SeverityLevel

if TYPE_CHECKING:
    from pathlib import Path


def _make_event(*, source_type: str = "syslog") -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        message="test",
        source_type=source_type,
        template_id=1,
        entity_refs=("user-001",),
        severity_id=SeverityLevel.INFORMATIONAL,
    )


class TestSaveAllState:
    async def test_save_persists_manifest_and_detectors(self) -> None:
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10, max_sources=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="syslog"))
        ensemble.process_event(_make_event(source_type="file"))

        storage = AsyncMock()
        storage.save_state = AsyncMock()
        count = await ensemble.save_all_state(storage)

        # Manifest + (4 detectors + 1 threshold + 1 window) * 2 sources + granular manifests
        assert count >= 10  # at least detectors + thresholds
        assert storage.save_state.call_count >= 11  # manifest + detectors + thresholds + windows

        # Verify ensemble manifest was saved
        saved_keys = [call[0][0] for call in storage.save_state.call_args_list]
        assert "ensemble:manifest" in saved_keys

    async def test_save_returns_count(self) -> None:
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10, max_sources=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event())

        storage = AsyncMock()
        storage.save_state = AsyncMock()
        count = await ensemble.save_all_state(storage)
        # 4 detectors + 1 threshold + 1 score window + 1 template HW + 1 entity HW
        assert count == 8


class TestLoadAllState:
    async def test_round_trip_restores_scores(self, tmp_path: Path) -> None:
        """Save → fresh ensemble → load → scores match."""
        from seerflow.config import DetectionConfig, StorageConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        # Use small calibration_window so threshold calibrates within test events
        config = DetectionConfig(
            hw_seasonal_period=10, max_sources=10, dspot_calibration_window=200
        )

        # Train and save — must process >= calibration_window events
        ensemble1 = DetectionEnsemble(config)
        for _ in range(210):
            ensemble1.process_event(_make_event())
        score_before = ensemble1.process_event(_make_event()).score
        await ensemble1.save_all_state(storage)

        # Fresh ensemble, load state
        ensemble2 = DetectionEnsemble(config)
        loaded = await ensemble2.load_all_state(storage)
        assert loaded >= 5  # at least detectors + threshold
        score_after = ensemble2.process_event(_make_event()).score

        # Scores should be similar (not exact due to threshold state)
        assert abs(score_before - score_after) < 0.1

        await storage.close()

    async def test_empty_storage_returns_zero(self) -> None:
        """No persisted state → load returns 0."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)

        storage = AsyncMock()
        storage.load_state = AsyncMock(return_value=None)
        count = await ensemble.load_all_state(storage)
        assert count == 0

    async def test_corrupt_state_uses_fresh_model(self) -> None:
        """Corrupt bytes → warning logged, fresh model used."""
        import msgspec.json

        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)

        storage = AsyncMock()
        # Return valid manifest but corrupt detector data
        manifest = msgspec.json.encode(["syslog"])

        async def fake_load(key: str) -> bytes | None:
            if key == "ensemble:manifest":
                return manifest
            if key.startswith("det:"):
                return b"corrupt-garbage-bytes"
            return None

        storage.load_state = AsyncMock(side_effect=fake_load)

        # load_all_state should handle corrupt data gracefully (no exception raised)
        count = await ensemble.load_all_state(storage)

        # Should have created detectors for "syslog" but failed to deserialize
        assert "syslog" in ensemble._detectors
        assert count == 0  # nothing successfully loaded

    async def test_corrupt_manifest_returns_zero(self) -> None:
        """Corrupt manifest bytes → warning logged, returns 0."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)

        storage = AsyncMock()
        storage.load_state = AsyncMock(return_value=b"not-valid-json")
        count = await ensemble.load_all_state(storage)
        assert count == 0

    async def test_corrupt_threshold_uses_fresh(self) -> None:
        """Corrupt threshold bytes → warning logged, fresh threshold."""
        import msgspec.json

        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)

        storage = AsyncMock()
        manifest = msgspec.json.encode(["syslog"])

        async def fake_load(key: str) -> bytes | None:
            if key == "ensemble:manifest":
                return manifest
            if key.startswith("thresh:"):
                return b"corrupt-threshold"
            return None

        storage.load_state = AsyncMock(side_effect=fake_load)
        count = await ensemble.load_all_state(storage)
        assert count == 0  # threshold failed, nothing else to load
        assert "syslog" in ensemble._detectors

    async def test_missing_detector_key_skipped(self) -> None:
        """Source in manifest but detector key missing → skip gracefully."""
        import msgspec.json

        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)

        storage = AsyncMock()
        manifest = msgspec.json.encode(["syslog"])

        async def fake_load(key: str) -> bytes | None:
            if key == "ensemble:manifest":
                return manifest
            return None  # all detector keys missing

        storage.load_state = AsyncMock(side_effect=fake_load)
        count = await ensemble.load_all_state(storage)
        assert count == 0
        assert "syslog" in ensemble._detectors  # detectors created but not loaded


class TestPersistenceHardening:
    async def test_manifest_written_last(self) -> None:
        """Manifest is the last key saved."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event())

        storage = AsyncMock()
        storage.save_state = AsyncMock()
        await ensemble.save_all_state(storage)

        # All manifests must be the last 3 keys saved (crash-safety)
        saved_keys = [call[0][0] for call in storage.save_state.call_args_list]
        manifests = {"tmpl_hw:manifest", "ent_hw:manifest", "ensemble:manifest"}
        assert set(saved_keys[-3:]) == manifests
        assert saved_keys[-1] == "ensemble:manifest"

    async def test_manifest_truncated_on_load(self) -> None:
        """Manifest with more sources than max_sources is truncated."""
        import msgspec.json

        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10, max_sources=2)
        ensemble = DetectionEnsemble(config)

        # Manifest with 5 sources but max_sources=2
        manifest = msgspec.json.encode(["s1", "s2", "s3", "s4", "s5"])
        storage = AsyncMock()

        async def fake_load(key: str) -> bytes | None:
            if key == "ensemble:manifest":
                return manifest
            return None

        storage.load_state = AsyncMock(side_effect=fake_load)

        await ensemble.load_all_state(storage)
        # Only first 2 sources should be loaded
        assert len(ensemble._detectors) <= 2
