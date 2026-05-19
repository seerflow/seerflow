"""Integration: streaming-scale LANL validation driver (S-309 / FR-077)."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"


@pytest.fixture(scope="module")
def streaming_result():
    from seerflow.lanl.streaming import run_streaming_validation

    return run_streaming_validation(FIXTURES_DIR, checkpoint_interval=25)


def test_streaming_result_has_combined_and_perf(streaming_result) -> None:
    r = streaming_result
    assert r.total_events_processed > 0
    assert 0.0 <= r.precision <= 1.0
    assert 0.0 <= r.recall <= 1.0
    assert r.throughput_events_per_s > 0.0
    assert r.mean_event_latency_s >= 0.0


def test_streaming_result_per_family_is_recognised(streaming_result) -> None:
    assert isinstance(streaming_result.per_family, dict)
    assert set(streaming_result.per_family).issubset(
        {"ml", "sigma", "correlation", "ueba", "ioc"}
    )


def test_two_streaming_runs_are_byte_identical() -> None:
    """AC3 determinism: same input → byte-identical combined + per-family."""
    import msgspec

    from seerflow.lanl.streaming import run_streaming_validation

    a = run_streaming_validation(FIXTURES_DIR, checkpoint_interval=25)
    b = run_streaming_validation(FIXTURES_DIR, checkpoint_interval=25)

    def keyed(r: object) -> tuple[object, ...]:
        return (
            r.true_positives,
            r.false_positives,
            r.false_negatives,
            r.precision,
            r.recall,
            r.f1_score,
            r.false_positive_rate,
            r.total_events_processed,
            msgspec.json.encode(
                {
                    k: (v.true_positives, v.false_positives, v.precision, v.f1_score)
                    for k, v in sorted(r.per_family.items())
                }
            ),
        )

    assert keyed(a) == keyed(b)
