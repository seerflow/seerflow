"""Unit tests for IoCEnrichmentMetrics + counters (S-069)."""

from __future__ import annotations

import pytest

from seerflow.threat_intel.enricher import (
    IoCEnrichmentMetrics,
    _IoCEnrichmentCounters,
)


@pytest.mark.unit
class TestIoCEnrichmentCounters:
    def test_initial_snapshot_is_zero(self) -> None:
        c = _IoCEnrichmentCounters()
        snap = c.snapshot()
        assert isinstance(snap, IoCEnrichmentMetrics)
        assert snap.alerts_emitted_total == 0
        assert snap.alerts_deduped_total == 0
        assert snap.dropped_entity_uuid_lookups_total == 0
        assert snap.risk_register_updates_total == 0

    def test_increments_are_monotonic(self) -> None:
        c = _IoCEnrichmentCounters()
        c.alerts_emitted_total += 1
        c.alerts_emitted_total += 2
        c.alerts_deduped_total += 1
        c.dropped_entity_uuid_lookups_total += 4
        c.risk_register_updates_total += 5
        snap = c.snapshot()
        assert snap.alerts_emitted_total == 3
        assert snap.alerts_deduped_total == 1
        assert snap.dropped_entity_uuid_lookups_total == 4
        assert snap.risk_register_updates_total == 5

    def test_snapshot_is_frozen(self) -> None:
        snap = _IoCEnrichmentCounters().snapshot()
        with pytest.raises(AttributeError):
            snap.alerts_emitted_total = 99  # type: ignore[misc]
