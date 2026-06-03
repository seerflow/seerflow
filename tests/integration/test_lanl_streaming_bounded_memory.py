"""Integration: streaming LANL bounded-memory regression (S-347).

Drives ``run_streaming_validation`` at three event-count sizes and asserts
that peak Python-heap memory stays *flat* -- i.e. does NOT grow linearly
with ``max_events``. The streaming path (S-309 / FR-077) is the path that
must ingest at billion-event scale, so this gate exists to catch the day
someone accidentally turns the bounded-memory guarantee back into
"memory grows with the dataset".

Doc reference: ``documents/testing-seerflow-against-lanl.md`` §7 item 3.

Why these specific numbers
--------------------------

The doc suggests 10k / 100k / 1M. A local probe on this worktree
(Python 3.11) measured 100k at >16 minutes wall-clock -- far outside the
per-PR CI budget the doc asks for. The story explicitly permits
downsizing because "the principle is the ratio not the absolute number",
so this test uses **500 / 2,500 / 10,000** instead. That keeps a single
in-test wall-clock under the ~80 s budget while still spanning a 20x
input range -- wide enough that a regression to linear growth would push
the peak ratio to ~20x and slam through any sane ceiling.

Calibration of the ratio ceiling
--------------------------------

Five independent measurements on this worktree (each preceded by a
100-event pre-warm to absorb one-time module-import + interpreter
steady-state allocations -- without the pre-warm the 500-event baseline
is inflated to ~130 MB by tracemalloc recording the imports themselves)::

    trial 0  peak(10k)/peak(500) = 1.612
    trial 1  peak(10k)/peak(500) = 1.628
    trial 2  peak(10k)/peak(500) = 1.625
    trial 3  peak(10k)/peak(500) = 1.626
    trial 4  peak(10k)/peak(500) = 1.589
    -------
    mean    ~ 1.616     range = 0.039  (~2.5 % relative)

That is sub-linear growth -- the pipeline holds bounded state, exactly as
S-309 designed. With this baseline, the chosen ``PEAK_RATIO_CEILING =
3.0`` gives ~1.86x headroom over the measured 1.62 +/- 0.02 envelope:
generous enough that the chosen tracemalloc jitter never trips it, but
tight enough that a true linear-memory regression (ratio ~20x) is caught
instantly. If steady-state pipeline allocations legitimately drift over
time, re-calibrate by re-running the probe and lowering the ceiling --
do NOT raise it to make a real regression pass.

Why tracemalloc and not RSS
---------------------------

* Deterministic -- tracemalloc counts only the Python interpreter's own
  heap allocations; OS page-cache + glibc arena slack do not perturb it.
* Lock-free, no subprocess -- compatible with the asyncio event loop that
  ``run_streaming_validation`` spins up internally via ``asyncio.run``.
* The 5-trial probe above held to ~2.5 % relative; RSS on the same
  hardware wobbled by tens of MB across runs, which would flake a tight
  regression gate.
* Trade-off: tracemalloc misses C-extension allocations (igraph,
  sqlite3). That is acceptable here -- the bounded-memory contract
  concerns Python-side state (handler stack, ensemble baselines, UEBA
  windows). A Python-side leak in those surfaces will register.
"""

from __future__ import annotations

import gc
import logging
import tracemalloc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# (events, expected to fit within the per-PR CI wall-time budget)
SIZES: tuple[int, ...] = (500, 2_500, 10_000)
PEAK_RATIO_CEILING: float = 3.0
PRE_WARM_EVENTS: int = 100


def _write_synthetic_lanl_dataset(out_dir: Path, n_events: int) -> None:
    """Emit minimal synthetic LANL-format CSVs totalling ~``n_events`` rows.

    The textual layout matches ``tests/fixtures/lanl/*.csv`` (verified
    against ``parser`` consumption). Composition: ~70 % auth, ~15 %
    proc, ~10 % flows, the remainder dns, plus a single 1-line redteam.
    This is generated per-test under ``tmp_path`` so no fixtures get
    committed and runs do not contaminate each other.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    n_auth = int(n_events * 0.70)
    n_proc = int(n_events * 0.15)
    n_flows = int(n_events * 0.10)
    n_dns = max(1, n_events - n_auth - n_proc - n_flows)

    # auth.csv: time,src_user,dst_user,src_comp,dst_comp,auth_type,logon_type,orientation,outcome
    with (out_dir / "auth.csv").open("w", encoding="utf-8") as f:
        for i in range(n_auth):
            t = i + 1
            u = (i % 50) + 1
            sc = (i % 100) + 1
            dc = ((i + 1) % 100) + 1
            f.write(f"{t},U{u}@DOM1,U{u}@DOM1,C{sc},C{dc},Kerberos,Network,LogOn,Success\n")

    # proc.csv: time,user,comp,proc_name,event
    with (out_dir / "proc.csv").open("w", encoding="utf-8") as f:
        for i in range(n_proc):
            t = i * 2 + 1
            u = (i % 50) + 1
            c = (i % 100) + 1
            f.write(f"{t},U{u}@DOM1,C{c},svchost.exe,Start\n")

    # flows.csv: time,duration,src_comp,src_port,dst_comp,dst_port,proto,packet_count,byte_count
    with (out_dir / "flows.csv").open("w", encoding="utf-8") as f:
        for i in range(n_flows):
            t = i * 3 + 1
            sc = (i % 100) + 1
            dc = ((i + 1) % 100) + 1
            f.write(f"{t},1,C{sc},12345,C{dc},443,6,10,1024\n")

    # dns.csv: time,src_comp,resolved_comp
    with (out_dir / "dns.csv").open("w", encoding="utf-8") as f:
        for i in range(n_dns):
            t = i * 5 + 1
            sc = (i % 100) + 1
            rc = ((i + 17) % 100) + 1
            f.write(f"{t},C{sc},C{rc}\n")

    # redteam.csv: time,user,src_comp,dst_comp
    (out_dir / "redteam.csv").write_text("100,U1@DOM1,C1,C2\n", encoding="utf-8")


def _measure_peak_bytes(dataset_dir: Path, max_events: int) -> tuple[int, int]:
    """Return ``(peak_bytes, total_events_processed)`` for one bounded streaming run.

    Each call owns its own tracemalloc session and runs ``gc.collect()``
    first so a previous iteration's garbage cannot inflate this peak.

    Returning ``total_events_processed`` lets the caller sanity-check
    that the run actually consumed the input: a silently-empty dataset
    would otherwise leave every iteration measuring the same
    module-init overhead, the ratio would trivially pass, and the test
    would prove nothing about bounded memory.

    The ``seerflow`` logger is muted at ERROR for the duration of the
    measurement. Reason: ``handler.py`` emits a WARNING for every
    detected anomaly, and pytest's log-capture handler retains every
    such record on the active test item. That retention scales
    *linearly* with ``max_events`` (more events -> more anomalies -> more
    captured log records) and would otherwise dominate the tracemalloc
    peak -- a measurement artefact, not a real bounded-memory breach.
    Outside pytest the standard root logger discards them at WARN level
    so the artefact does not appear; the silencing is purely defensive.
    """
    from seerflow.lanl.streaming import run_streaming_validation

    _seerflow_log = logging.getLogger("seerflow")
    prior_level = _seerflow_log.level
    _seerflow_log.setLevel(logging.ERROR)
    try:
        gc.collect()
        tracemalloc.start()
        try:
            result = run_streaming_validation(dataset_dir, max_events=max_events)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    finally:
        _seerflow_log.setLevel(prior_level)
    return peak, int(result.total_events_processed)


def test_streaming_peak_memory_stays_flat_across_sizes(tmp_path: Path) -> None:
    """Peak traced memory must not grow with ``max_events`` (bounded contract).

    Specifically: ``peak(SIZES[-1]) / peak(SIZES[0])`` must stay below
    ``PEAK_RATIO_CEILING``. The probe documented in the module docstring
    showed sub-linear ~1.62x growth across a 20x input range -- the
    chosen ceiling (3.0) leaves ~1.86x headroom over that envelope.
    """
    # Pre-warm: absorb one-time module-import + interpreter-state cost
    # that would otherwise inflate the first measured iteration's peak by
    # an order of magnitude (probe showed ~130 MB on first call vs ~8 MB
    # on the second call). Discard its measurement.
    pre = tmp_path / "ds_prewarm"
    _write_synthetic_lanl_dataset(pre, PRE_WARM_EVENTS)
    _measure_peak_bytes(pre, PRE_WARM_EVENTS)

    peaks: dict[int, int] = {}
    processed: dict[int, int] = {}
    for n in SIZES:
        ds = tmp_path / f"ds_{n}"
        _write_synthetic_lanl_dataset(ds, n)
        peaks[n], processed[n] = _measure_peak_bytes(ds, n)

    # Sanity: a zero or negative peak means the measurement broke, not
    # that the contract held -- fail loudly rather than silently passing.
    assert peaks[SIZES[-1]] > 0, f"tracemalloc returned non-positive peak: {peaks}"
    assert peaks[SIZES[0]] > 0, f"tracemalloc returned non-positive peak: {peaks}"

    # Guard against the silent-empty-stream trap: if the synthetic dataset
    # generator drifted out of sync with the parser and produced 0 events,
    # peaks would be ~flat (just module-init overhead) and the ratio check
    # below would pass trivially without proving anything. Require each
    # iteration to have consumed at least 90 % of its target.
    for n in SIZES:
        assert processed[n] >= int(n * 0.9), (
            f"streaming run consumed only {processed[n]} of {n} requested events "
            f"-- the synthetic dataset generator may have drifted out of sync "
            f"with the LANL parser. processed={processed}"
        )

    ratio = peaks[SIZES[-1]] / peaks[SIZES[0]]
    assert ratio < PEAK_RATIO_CEILING, (
        f"streaming peak memory grew {ratio:.2f}x across {SIZES[0]} -> "
        f"{SIZES[-1]} events (expected < {PEAK_RATIO_CEILING:.1f}x). "
        f"Peaks (bytes): {peaks}. This signals a regression in the "
        f"bounded-memory guarantee -- investigate the streaming path "
        f"(src/seerflow/lanl/streaming.py) before relaxing this ceiling."
    )
