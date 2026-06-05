"""Smoke test: the S-356 per-event throughput benchmark reports a positive eps."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


def test_bench_measure_accepts_hst_overrides() -> None:
    """S-360: ``_measure`` accepts optional HST n_trees/window_size overrides so a
    single script reproduces the old (25/1000) and new (10/250) eps numbers."""
    from tests.perf.bench_s356_throughput import _measure

    n, _timed_events, _elapsed, eps = _measure(_FIXTURE, passes=1, n_trees=25, window_size=1000)
    assert n > 0
    assert eps > 0.0


def test_bench_main_accepts_hst_override_flags(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """S-360: ``--n-trees`` / ``--window-size`` flags are parsed and printed."""
    from tests.perf.bench_s356_throughput import _main

    monkeypatch.setattr(
        "sys.argv",
        [
            "bench",
            "--passes",
            "1",
            "--dataset",
            str(_FIXTURE),
            "--n-trees",
            "10",
            "--window-size",
            "250",
        ],
    )
    rc = _main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "per_event_eps=" in out
    assert "n_trees=10" in out
    assert "window_size=250" in out
