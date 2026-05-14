"""S-082 — verify ``collect_memory_bounds`` projects ``DetectionEnsemble``
state into four stable audit keys.

The ensemble already tracks bound state internally (S-025, S-091); this
test proves the adapter renames its keys without recomputation.
"""

from __future__ import annotations

import uuid

import pytest

from seerflow.config import DetectionConfig
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.models import SeerflowEvent, SeverityLevel
from seerflow.utils.memory_bounds import collect_memory_bounds


def _event(source: str) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        message="test",
        severity_id=SeverityLevel.INFORMATIONAL,
        source_type=source,
    )


@pytest.mark.unit
def test_ensemble_projection_into_audit_keys() -> None:
    cfg = DetectionConfig(
        hw_seasonal_period=10,
        dspot_calibration_window=200,
        max_sources=64,
        max_template_hw=32,
        max_entity_hw=16,
    )
    ens = DetectionEnsemble(cfg)
    for source in ("syslog", "windows", "linux"):
        ens.process_event(_event(source))

    bounds = collect_memory_bounds(ensemble=ens)
    assert set(bounds) >= {
        "ensemble.sources",
        "ensemble.template_hw",
        "ensemble.entity_hw",
        "ensemble.markov",
    }
    assert bounds["ensemble.sources"]["current"] == 3
    assert bounds["ensemble.sources"]["max"] == 64
    assert bounds["ensemble.sources"]["evictions"] == 0

    # template_hw / entity_hw counts are populated lazily; they may be
    # zero on a freshly-processed event, but the audit must still report
    # the configured cap.
    assert bounds["ensemble.template_hw"]["max"] == 32
    assert bounds["ensemble.entity_hw"]["max"] == 16

    # Markov aggregate cap is per_source * sources (or per_source when no
    # sources are warm yet).
    assert bounds["ensemble.markov"]["max"] >= 1


@pytest.mark.unit
def test_ensemble_eviction_count_propagates() -> None:
    cfg = DetectionConfig(
        hw_seasonal_period=10,
        dspot_calibration_window=200,
        max_sources=2,
    )
    ens = DetectionEnsemble(cfg)
    for source in ("a", "b", "c", "d", "e"):
        ens.process_event(_event(source))

    bounds = collect_memory_bounds(ensemble=ens)
    # 5 unique sources, cap=2, so 3 LRU evictions on the source slot.
    assert bounds["ensemble.sources"]["current"] == 2
    assert bounds["ensemble.sources"]["max"] == 2
    assert bounds["ensemble.sources"]["evictions"] == 3
