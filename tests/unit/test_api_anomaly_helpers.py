"""Pure helper / struct tests for seerflow.api.anomaly_timeline."""

from __future__ import annotations

import pytest

from seerflow.api.anomaly_timeline import (
    BUCKET_NS,
    RANGE_NS,
    RESOLUTION_NS,
    TimelineBucket,
    allowed_resolutions,
    bucket_index,
    default_resolution,
)


@pytest.mark.unit
class TestBucketHelpers:
    def test_bucket_ns_is_one_minute(self) -> None:
        assert BUCKET_NS == 60 * 1_000_000_000

    @pytest.mark.parametrize(
        ("res", "expected"),
        [("1m", 60), ("5m", 300), ("15m", 900), ("1h", 3600)],
    )
    def test_resolution_ns(self, res: str, expected: int) -> None:
        assert RESOLUTION_NS[res] == expected * 1_000_000_000

    @pytest.mark.parametrize(
        ("rng", "expected_s"),
        [("1h", 3600), ("6h", 21600), ("24h", 86400), ("7d", 604800)],
    )
    def test_range_ns(self, rng: str, expected_s: int) -> None:
        assert RANGE_NS[rng] == expected_s * 1_000_000_000

    @pytest.mark.parametrize(
        ("rng", "resolutions"),
        [
            ("1h", ("1m",)),
            ("6h", ("1m", "5m")),
            ("24h", ("5m", "15m")),
            ("7d", ("15m", "1h")),
        ],
    )
    def test_allowed_resolutions_matrix(self, rng: str, resolutions: tuple[str, ...]) -> None:
        assert allowed_resolutions(rng) == resolutions

    @pytest.mark.parametrize(
        ("rng", "expected"),
        [("1h", "1m"), ("6h", "1m"), ("24h", "5m"), ("7d", "15m")],
    )
    def test_default_resolution(self, rng: str, expected: str) -> None:
        assert default_resolution(rng) == expected

    def test_bucket_index_floor_divides(self) -> None:
        assert bucket_index(0) == 0
        assert bucket_index(BUCKET_NS) == 1
        assert bucket_index(BUCKET_NS + 1) == 1
        assert bucket_index(2 * BUCKET_NS - 1) == 1

    def test_timeline_bucket_struct_has_expected_fields(self) -> None:
        b = TimelineBucket(
            bucket_start_ns=0,
            max_score=0.5,
            avg_score=0.25,
            event_count=2,
            upper_threshold=0.85,
            alert_count=0,
        )
        assert b.bucket_start_ns == 0
        assert b.max_score == 0.5
        assert b.avg_score == 0.25
        assert b.event_count == 2
        assert b.upper_threshold == 0.85
        assert b.alert_count == 0
