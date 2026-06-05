"""Smoke test: the S-356 per-event throughput benchmark reports a positive eps."""

from __future__ import annotations

from pathlib import Path

import pytest

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "lanl"


def test_bench_measure_reports_positive_eps() -> None:
    """``_measure`` drives the handler over the fixture and reports a finite eps."""
    from tests.perf.bench_s356_throughput import _measure

    n, timed_events, elapsed, eps = _measure(_FIXTURE, passes=1)
    assert n > 0
    assert timed_events == n  # one timed pass
    assert elapsed > 0.0
    assert eps > 0.0


def test_bench_main_prints_eps(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_main`` parses args and prints a per-event eps line."""
    from tests.perf.bench_s356_throughput import _main

    monkeypatch.setattr("sys.argv", ["bench", "--passes", "1", "--dataset", str(_FIXTURE)])
    rc = _main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "per_event_eps=" in out
    eps = float(out.split("per_event_eps=")[1].strip())
    assert eps > 0.0
