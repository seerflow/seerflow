"""Integration tests — S-201 reverse HW index round-trips through real SqliteBackend.

Covers the CLAUDE.md backend PR hard gate: pipeline stages with real storage.
Unit coverage lives in ``tests/unit/test_detection_ensemble.py`` (TestLoadStateReverseIndex);
this file exercises the same invariants through the public ``save_all_state`` /
``load_all_state`` round-trip without fixture mocks.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from seerflow.config import DetectionConfig
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.models import SeerflowEvent, SeverityLevel

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


def _event(
    *, source_type: str = "syslog", template_id: int = 0, entity_refs: tuple[str, ...] = ()
) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        message="integration test",
        template_id=template_id,
        severity_id=SeverityLevel.INFORMATIONAL,
        source_type=source_type,
        entity_refs=entity_refs,
    )


def _config() -> DetectionConfig:
    return DetectionConfig(
        hw_seasonal_period=10,
        dspot_calibration_window=200,
        max_sources=4,
        max_template_hw=16,
        max_entity_hw=16,
    )


class TestEnsembleReverseIndexPersistence:
    @pytest.mark.asyncio
    async def test_round_trip_preserves_reverse_index(self, backend: SqliteBackend) -> None:
        """save_all_state → load_all_state rebuilds _source_hw_keys consistently."""
        src = DetectionEnsemble(_config())
        src.process_event(_event(source_type="api", template_id=1, entity_refs=("u1",)))
        src.process_event(_event(source_type="api", template_id=2))
        src.process_event(_event(source_type="worker", template_id=9, entity_refs=("u2",)))
        await src.save_all_state(backend)

        dst = DetectionEnsemble(_config())
        await dst.load_all_state(backend)

        assert dst._source_hw_keys["api"][0] == {"api:1", "api:2"}
        assert dst._source_hw_keys["api"][1] == {"api:u1"}
        assert dst._source_hw_keys["worker"][0] == {"worker:9"}
        assert dst._source_hw_keys["worker"][1] == {"worker:u2"}

    @pytest.mark.asyncio
    async def test_round_trip_sanitizes_colon_sources(self, backend: SqliteBackend) -> None:
        """Sources with colons sanitize on write AND on load, key shape stable end-to-end."""
        src = DetectionEnsemble(_config())
        src.process_event(_event(source_type="syslog:prod", template_id=5))
        await src.save_all_state(backend)

        dst = DetectionEnsemble(_config())
        await dst.load_all_state(backend)

        # Sanitized form is the only on-disk shape; no colon-laden keys survive.
        assert all(":" not in s for s in dst._detectors)
        assert "syslog_prod" in dst._source_hw_keys
        assert dst._source_hw_keys["syslog_prod"][0] == {"syslog_prod:5"}

    @pytest.mark.asyncio
    async def test_source_eviction_after_reload_uses_reverse_index(
        self, backend: SqliteBackend
    ) -> None:
        """Reloaded state keeps the reverse-index → eviction is O(k), not a prefix scan."""
        src = DetectionEnsemble(_config())
        for tid in range(3):
            src.process_event(_event(source_type="srcA", template_id=tid))
        for tid in range(3):
            src.process_event(_event(source_type="srcB", template_id=tid))
        await src.save_all_state(backend)

        dst = DetectionEnsemble(_config())
        await dst.load_all_state(backend)

        # Push three more sources to force LRU eviction of srcA on the reloaded instance.
        for src_name in ("srcC", "srcD", "srcE"):
            dst.process_event(_event(source_type=src_name, template_id=0))

        assert "srcA" not in dst._detectors
        assert "srcA" not in dst._source_hw_keys
        assert all(not k.startswith("srcA:") for k in dst._template_hw)
