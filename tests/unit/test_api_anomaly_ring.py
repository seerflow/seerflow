"""Tests for AnomalyTimelineRing record + query."""

from __future__ import annotations

import pytest

from seerflow.api.anomaly_timeline import (
    BUCKET_NS,
    RANGE_NS,
    RESOLUTION_NS,
    AnomalyTimelineRing,
)


@pytest.mark.unit
class TestAnomalyTimelineRing:
    def test_record_single_event_one_bucket(self) -> None:
        ring = AnomalyTimelineRing(capacity_buckets=10)
        ring.record_score(BUCKET_NS * 3 + 500, 0.5, 0.9, "syslog")
        out = ring.query(
            range_ns=RANGE_NS["1h"],
            resolution_ns=RESOLUTION_NS["1m"],
            source=None,
            now_ns=BUCKET_NS * 3 + 500,
        )
        bucket_with_data = [b for b in out if b.event_count > 0]
        assert len(bucket_with_data) == 1
        assert bucket_with_data[0].max_score == 0.5
        assert bucket_with_data[0].avg_score == 0.5
        assert bucket_with_data[0].event_count == 1
        assert bucket_with_data[0].upper_threshold == 0.9

    def test_record_merges_within_same_bucket(self) -> None:
        ring = AnomalyTimelineRing(capacity_buckets=10)
        ts = BUCKET_NS * 2
        ring.record_score(ts, 0.3, 0.9, "syslog")
        ring.record_score(ts + 100, 0.7, 0.9, "syslog")
        ring.record_score(ts + 200, 0.5, 0.9, "syslog")
        out = ring.query(
            range_ns=RANGE_NS["1h"],
            resolution_ns=RESOLUTION_NS["1m"],
            source=None,
            now_ns=ts + 1000,
        )
        hit = [b for b in out if b.event_count > 0]
        assert len(hit) == 1
        assert hit[0].event_count == 3
        assert hit[0].max_score == 0.7
        assert hit[0].avg_score is not None
        assert abs(hit[0].avg_score - (0.3 + 0.7 + 0.5) / 3) < 1e-9

    def test_downsample_five_base_buckets_into_one_five_minute_bucket(self) -> None:
        ring = AnomalyTimelineRing(capacity_buckets=100)
        base = BUCKET_NS * 10
        for i in range(5):
            ring.record_score(base + i * BUCKET_NS, 0.1 * (i + 1), 0.9, "syslog")
        out = ring.query(
            range_ns=RANGE_NS["1h"],
            resolution_ns=RESOLUTION_NS["5m"],
            source=None,
            now_ns=base + 5 * BUCKET_NS,
        )
        hit = [b for b in out if b.event_count > 0]
        assert len(hit) == 1
        assert hit[0].event_count == 5
        assert hit[0].max_score == pytest.approx(0.5)
        assert hit[0].avg_score == pytest.approx((0.1 + 0.2 + 0.3 + 0.4 + 0.5) / 5)

    def test_threshold_carry_forward_across_empty_buckets(self) -> None:
        ring = AnomalyTimelineRing(capacity_buckets=10)
        ring.record_score(BUCKET_NS * 1, 0.5, 0.9, "syslog")
        ring.record_score(BUCKET_NS * 3, 0.4, 0.95, "syslog")
        out = ring.query(
            range_ns=RANGE_NS["1h"],
            resolution_ns=RESOLUTION_NS["1m"],
            source=None,
            now_ns=BUCKET_NS * 3 + 500,
        )
        empty = next(b for b in out if b.bucket_start_ns == BUCKET_NS * 2)
        assert empty.event_count == 0
        assert empty.upper_threshold == 0.9
        b3 = next(b for b in out if b.bucket_start_ns == BUCKET_NS * 3)
        assert b3.upper_threshold == 0.95

    def test_source_filter(self) -> None:
        ring = AnomalyTimelineRing(capacity_buckets=10)
        ts = BUCKET_NS * 5
        ring.record_score(ts, 0.8, 0.9, "syslog")
        ring.record_score(ts, 0.2, 0.9, "otlp")
        out = ring.query(
            range_ns=RANGE_NS["1h"],
            resolution_ns=RESOLUTION_NS["1m"],
            source="syslog",
            now_ns=ts + 100,
        )
        hit = [b for b in out if b.event_count > 0]
        assert hit[0].max_score == 0.8
        assert hit[0].event_count == 1

    def test_source_none_returns_max_threshold_across_sources(self) -> None:
        ring = AnomalyTimelineRing(capacity_buckets=10)
        ts = BUCKET_NS * 5
        ring.record_score(ts, 0.8, 0.9, "syslog")
        ring.record_score(ts, 0.2, 1.2, "otlp")
        out = ring.query(
            range_ns=RANGE_NS["1h"],
            resolution_ns=RESOLUTION_NS["1m"],
            source=None,
            now_ns=ts + 100,
        )
        hit = [b for b in out if b.event_count > 0]
        assert hit[0].upper_threshold == pytest.approx(1.2)
        assert hit[0].event_count == 2
        assert hit[0].max_score == pytest.approx(0.8)

    def test_wrap_around_past_capacity_discards_oldest(self) -> None:
        ring = AnomalyTimelineRing(capacity_buckets=3)
        ring.record_score(BUCKET_NS * 10, 0.1, 0.9, "syslog")
        ring.record_score(BUCKET_NS * 11, 0.2, 0.9, "syslog")
        ring.record_score(BUCKET_NS * 12, 0.3, 0.9, "syslog")
        ring.record_score(BUCKET_NS * 13, 0.4, 0.9, "syslog")
        out = ring.query(
            range_ns=RANGE_NS["1h"],
            resolution_ns=RESOLUTION_NS["1m"],
            source=None,
            now_ns=BUCKET_NS * 13 + 500,
        )
        found = {b.bucket_start_ns for b in out if b.event_count > 0}
        assert BUCKET_NS * 10 not in found
        assert {BUCKET_NS * 11, BUCKET_NS * 12, BUCKET_NS * 13}.issubset(found)

    def test_source_cap_evicts_oldest_when_exceeded(self) -> None:
        ring = AnomalyTimelineRing(capacity_buckets=5, max_sources=2)
        ts = BUCKET_NS
        ring.record_score(ts, 0.1, 0.9, "s1")
        ring.record_score(ts, 0.2, 0.9, "s2")
        ring.record_score(ts, 0.3, 0.9, "s3")
        out = ring.query(
            range_ns=RANGE_NS["1h"],
            resolution_ns=RESOLUTION_NS["1m"],
            source="s1",
            now_ns=ts + 100,
        )
        hit = [b for b in out if b.event_count > 0]
        assert hit == []

    def test_query_returns_only_buckets_within_range(self) -> None:
        ring = AnomalyTimelineRing(capacity_buckets=100)
        for i in range(10):
            ring.record_score(BUCKET_NS * i, 0.1 * (i + 1), 0.9, "syslog")
        now = BUCKET_NS * 10
        out = ring.query(
            range_ns=RANGE_NS["1h"],
            resolution_ns=RESOLUTION_NS["1m"],
            source=None,
            now_ns=now,
        )
        assert len(out) == 60
        starts = [b.bucket_start_ns for b in out]
        assert starts == sorted(starts)
