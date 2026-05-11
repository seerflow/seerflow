"""Unit tests for confidence → severity mapping (S-069)."""

from __future__ import annotations

import pytest

from seerflow.threat_intel.enricher import (
    _clamp_confidence,
    _severity_for_confidence,
)


@pytest.mark.unit
class TestClampConfidence:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(-5, 0), (0, 0), (50, 50), (100, 100), (150, 100)],
    )
    def test_clamps_to_0_100(self, raw: int, expected: int) -> None:
        assert _clamp_confidence(raw) == expected


@pytest.mark.unit
class TestSeverityForConfidence:
    @pytest.mark.parametrize(
        ("confidence", "expected_severity"),
        [
            (0, 2),
            (32, 2),
            (33, 3),
            (50, 3),
            (66, 3),
            (67, 4),
            (84, 4),
            (85, 5),
            (99, 5),
            (100, 5),
        ],
    )
    def test_band_mapping(self, confidence: int, expected_severity: int) -> None:
        assert _severity_for_confidence(confidence) == expected_severity
