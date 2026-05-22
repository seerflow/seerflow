# Testing Seerflow Against the LANL Dataset

A step-by-step tutorial for validating Seerflow's detection accuracy and
performance against the **LANL 2015 "Comprehensive, Multi-Source
Cyber-Security Events"** dataset (Los Alamos National Laboratory), plus a
catalog of additional tests that build confidence the system really works.

> **About the dataset:** the LANL 2015 set is 58 days of de-identified activity
> from Los Alamos National Laboratory's real enterprise network — ~1.65 billion
> authentication, process, network-flow, and DNS events. Crucially it ships a
> red-team **ground-truth** label file, so detection accuracy can actually be
> scored. Full schema, scale, and field details:
> [lanl-2015-dataset.md](./lanl-2015-dataset.md).

> **TL;DR**
> - **Smoke test (no download):** `uv run python -m seerflow validate tests/fixtures/lanl`
> - **Combined scorecard:** `uv run python -m seerflow benchmark --scorecard`
> - **Real accuracy:** download the full dataset (`python -m seerflow.lanl.fetch`), then point `validate` at it; use the streaming API for billion-event scale.

---

## 1. What the harness actually exercises

As of S-305 (FR-073 AC6) the LANL harness drives the **full detection stack**
— the *identical* wiring as a live `seerflow start`:

```
RawEvent → Drain3 (template extraction) → entity extraction
         → ML ensemble (Half-Space Trees, Holt-Winters, CUSUM, Markov)
         → Sigma rules → UEBA → IoC → Correlation
         → SQLite persistence → alerts scored vs red-team ground truth
```

It is **regression-guarded** (`tests/integration/test_lanl_full_stack_regression.py`):
the test asserts `validator.py` contains `assemble_handler` and does **not**
construct a bare `CorrelationEngine`, so the harness can never silently revert
to a correlation-only path.

**What it does NOT exercise** (covered by other tests — see §7):

| Skipped | Why | How to cover it |
|---------|-----|-----------------|
| Receivers (syslog/OTLP/file/webhook) | Events are injected directly as `RawEvent` objects | Live E2E with `seerflow start` + a replay feeder |
| Dashboard / HTTP API | No server runs during validation | Live E2E |
| Real-time streaming ingest | Records are replayed in batch against a frozen clock | `run_streaming_validation` (bounded-memory path) |

---

## 2. Prerequisites

```bash
uv sync                 # install dependencies
uv run pytest -q        # sanity-check the environment (optional)
```

Run all commands from the repo root (`/home/fflores/PycharmProjects/seerflow`).
The `uv run python -m seerflow ...` form is used throughout; the `seerflow`
console script is equivalent if the package is installed in the venv.

---

## 3. Part A — Quick start on the committed synthetic subset

A tiny, **committed, synthetic** LANL subset lives in `tests/fixtures/lanl/`:

```
auth.csv     # ~50 authentication records
proc.csv     # process start/stop
flows.csv    # network flows
redteam.csv  # 6 ground-truth red-team labels
dns.csv      # optional DNS records
```

This is the fast smoke test — **no download, ~1 second** — and the default
dataset for `benchmark --scorecard`. It is **not** a real accuracy benchmark
(see §3.3 for why the numbers are low).

### 3.1 Run the accuracy harness

```bash
uv run python -m seerflow validate tests/fixtures/lanl
```

Expected output (real, deterministic — byte-identical on every machine):

```
metric                  value
----------------------  ----------------------------------------------------
precision               0.16666666666666666
recall                  0.3333333333333333
f1                      0.2222222222222222
false_positive_rate     0.8333333333333334
auc                     0.0
attack_scenarios        [brute-force-lateral-movement (detected=False),
                         credential-stuffing       (detected=False),
                         c2-beaconing              (detected=True, mttd=300.0s)]
true_positives          2
false_positives         10
false_negatives         4
total_events_processed  137
total_alerts            12
patterns_detected       ['c2-beaconing']
dataset_dir             tests/fixtures/lanl
```

> **Note:** the run is now clean of `Unknown ATT&CK tactic` warnings. Earlier
> builds emitted ~40 of them; valid hyphenated tactic tags
> (`command-and-control`) are normalized to canonical form, and MITRE Software
> IDs that SigmaHQ tags on rules (e.g. `attack.s0508` = Ngrok) are recognized
> and ignored rather than mistaken for unknown tactics.

### 3.2 Machine-readable output

```bash
uv run python -m seerflow validate tests/fixtures/lanl --json
```

Emits one JSON object (precision/recall/f1/fpr/auc, per-scenario MTTD,
`pr_points`/`roc_points` curves, and `missed_attributions` naming the *silent
detector family* for every missed red-team record). Pipe to `jq` for slicing:

```bash
uv run python -m seerflow validate tests/fixtures/lanl --json 2>/dev/null \
  | jq '{precision, recall, f1, auc, scenarios: .attack_scenarios}'
```

### 3.3 How to read these numbers (important)

The synthetic numbers are **low on purpose** and prove *mechanics, not
product accuracy*:

- Only **137 events** and **6 red-team labels** — far too small for stable
  precision/recall.
- `c2-beaconing` is **detected** (MTTD 300 s); `brute-force-lateral-movement`
  and `credential-stuffing` are **missed**, attributed to the silent
  `correlation` family in `missed_attributions`.
- `auc = 0.0` is **degenerate** here — a threshold sweep over a handful of
  alerts can't form a meaningful ROC curve. On the full dataset it becomes a
  real area-under-curve.

**Use Part A to confirm the pipeline runs end-to-end and is deterministic.
Use Part B for an accuracy claim you can publish.**

### 3.4 Combined scorecard (accuracy + performance)

```bash
uv run python -m seerflow benchmark --scorecard
```

Runs accuracy (on `tests/fixtures/lanl` by default) **and** a synthetic
throughput benchmark, printing one consolidated table. `--scorecard` is
human-readable by contract — `--json` is ignored in this mode. Knobs:

```bash
uv run python -m seerflow benchmark --scorecard \
  --dataset-dir /path/to/full/lanl \   # accuracy dataset
  --count 50000 \                       # synthetic events for the perf section
  --seed 42                             # deterministic RNG
```

Example performance section (`--count 2000`):

```
### Performance
metric           value
---------------  ------------------
event_count      2000
throughput_eps   ~1400
latency_p50_ms   ~0.61
latency_p95_ms   ~1.17
peak_rss_mb      ~228
alerts           498
seed             42
```

(Throughput/RSS are machine-dependent; treat them as a local baseline, not an
absolute SLO.)

---

## 4. Part B — Testing against the full LANL 2015 dataset

The full dataset is the real benchmark: **~1.6 billion events** across four
files, sourced from <https://csr.lanl.gov/data/cyber1/>.

### 4.1 Download + verify

```bash
uv run python -m seerflow.lanl.fetch --dest /data/lanl
```

This downloads, SHA-256-verifies, and unpacks `auth.csv`, `proc.csv`,
`flows.csv`, and `redteam.csv` into the validator's expected layout. It
supports resumable downloads (HTTP Range).

> **⚠️ Manifest caveat:** the *pinned* manifest in `fetch.py`
> (`LANL_2015_MANIFEST`) ships with **placeholder digests** (`"0"*64`).
> For a real run you must supply your own manifest with actual checksums:
> ```bash
> uv run python -m seerflow.lanl.fetch --dest /data/lanl --manifest my-manifest.json
> ```
> Use `--manifest` for an internal mirror with its own digests. Without a
> valid manifest the verification step will reject the download.

**Expected dataset shape** (uncompressed ≈ 10–15 GB):

| File | Columns |
|------|---------|
| `auth.csv` | `time, src_user, dst_user, src_computer, dst_computer, auth_type, logon_type, auth_orientation, success/fail` |
| `proc.csv` | `time, user, computer, process_name, start/end` |
| `flows.csv` | `time, duration, src_computer, src_port, dst_computer, dst_port, protocol, packet_count, byte_count` |
| `redteam.csv` | `time, user, src_computer, dst_computer` (ground truth) |

### 4.2 Run accuracy against the full set

```bash
uv run python -m seerflow validate /data/lanl --json > lanl-result.json
```

⚠️ The default `validate` path (`run_validation`) loads records **in memory**.
That is fine for the synthetic subset and for bounded slices, but the full
dataset will exhaust RAM. For the full set, use the streaming path (§4.3).

To test a **bounded slice** with the in-memory path, pre-truncate the CSVs
(e.g. one day of `auth.csv`) into a separate directory and point `validate`
at that directory.

### 4.3 Streaming path for billion-event scale

For the full dataset, use the **bounded-memory, resumable** streaming harness
(S-309 / FR-077). It is a Python API (no CLI yet):

```bash
uv run python - <<'PY'
from pathlib import Path
from seerflow.lanl.streaming import run_streaming_validation

result = run_streaming_validation(
    Path("/data/lanl"),
    checkpoint_interval=10_000,   # checkpoint every N events (resumable)
    max_events=1_000_000,         # cap the run; None = whole dataset
)
print("precision", result.precision, "recall", result.recall, "f1", result.f1_score)
print("throughput_eps", result.throughput_eps)
PY
```

- **Bounded memory:** k-way merge across the four CSVs — never loads the full
  dataset into RAM.
- **Resumable:** checkpoints every `checkpoint_interval` events.
- **`max_events`:** caps the run for a quick large-but-not-full pass.
- Returns a `StreamingValidationResult` — a transparent `ValidationResult`
  passthrough plus `throughput_eps` / latency fields.

### 4.4 Pure throughput/latency benchmark

```bash
uv run python -m seerflow benchmark --count 1000000 --seed 42
# or JSON:
uv run python -m seerflow benchmark --count 1000000 --json
```

Drives synthetic syslog events through the same handler and reports
throughput (events/s), latency p50/p95/mean, peak RSS, and alert count. This
measures the *engine*, not LANL accuracy.

---

## 5. What "good" looks like

| Signal | Synthetic subset | Full dataset (target) |
|--------|------------------|------------------------|
| Pipeline runs end-to-end | ✅ required | ✅ required |
| Determinism (same input → same metrics) | ✅ guaranteed (frozen clock) | ✅ guaranteed |
| Precision / Recall / F1 | low (tiny fixture) | the real claim — compare vs published LANL baselines |
| AUC | `0.0` (degenerate) | a real ROC area in `(0,1)` |
| Per-scenario MTTD | c2 only | every scenario should have a finite MTTD |
| `missed_attributions` empty | no | ideally yes (every red-team event covered) |
| Peak RSS (streaming) | n/a | **flat** as `max_events` grows |

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `Unknown ATT&CK tactic '...'` warning | Should no longer appear. Hyphenated tactic tags are normalized (`command-and-control` → `command_and_control`) and MITRE Software IDs (`attack.s0508`) are ignored. If you still see one, it's a genuinely unknown/malformed `attack.` tag in a custom rule — check that rule's tags. |
| `Error: dataset directory not found: ...` (exit 2) | The path isn't a directory. `validate` checks before running. |
| `DatasetVerificationError` on fetch | Placeholder/wrong manifest digests — supply a valid `--manifest`. |
| OOM on full dataset with `validate` | Use the streaming path (§4.3), not the in-memory `validate`. |
| Metrics differ between machines | Should never happen — file a bug; the frozen replay clock (`REPLAY_EPOCH_NS`) makes runs byte-identical. |

---

## 7. Additional tests to prove it really works

The LANL harness alone is necessary but not sufficient. Layer these to build
real confidence:

1. **Determinism guard.** Run `validate --json` twice and `diff` the output —
   they must be byte-identical. Already covered by
   `tests/integration/test_lanl_harness_determinism.py`; re-run on any change
   touching correlation/window/risk.

2. **Full-stack wiring guard.** Keep `test_lanl_full_stack_regression.py`
   green — it's the canary against silently dropping detector families.

3. **Streaming memory test.** Run `run_streaming_validation` with
   `max_events` at 10k / 100k / 1M and record peak RSS at each. Peak memory
   should stay **flat** — if it grows with `max_events`, the bounded-memory
   guarantee is broken.

4. **Checkpoint/resume test.** Kill a streaming run mid-way, restart it, and
   confirm the final metrics match an uninterrupted run — proves resumability.

5. **False-positive baseline (benign-only).** Feed a benign log sample with
   **no** red-team activity and confirm a low alert rate / FPR. High FPR on
   benign traffic is the most common way a "high recall" detector is actually
   useless in production.

6. **Per-detector ablation.** Use the `per_family` block in the result to see
   which families (`ml`, `sigma`, `correlation`, `ueba`, `ioc`) carry
   detections. If recall depends entirely on one family, that's fragility —
   investigate why the others are silent (see `missed_attributions`).

7. **Comparison vs published baselines.** Plot recall at a fixed
   false-positive budget and compare against published LANL anomaly-detection
   results. "Better than random" (AUC > 0.5) is the floor; competitive recall
   at low FPR is the goal.

8. **Threshold-sweep / ROC sanity.** On the full dataset, plot `roc_points`
   and confirm a monotonic, non-degenerate curve. Pick an operating threshold
   from the PR curve rather than the default.

9. **MTTD distribution.** Check `mttd_seconds` per scenario — detection that
   only fires hours after the kill-chain starts has limited operational value.

10. **Live E2E (closes the receiver/dashboard gap).** Replay LANL records over
    a real syslog/OTLP receiver into `seerflow start`, then verify alerts via
    the dashboard/API. This is the only test that exercises the ingestion and
    serving paths the offline harness skips.

11. **Throughput SLO test.** Run `benchmark --count <large>` and assert
    throughput/latency meet the NFR targets on representative hardware. Wire
    this into CI as a regression gate.

12. **Scale soak.** Run the streaming path over the full ~1.6B-event dataset
    end-to-end and confirm it completes without OOM, with stable throughput.

---

## 8. References

| Item | Location |
|------|----------|
| Accuracy harness | `src/seerflow/lanl/validator.py` (`run_validation`, `run_validation_async`) |
| Streaming harness | `src/seerflow/lanl/streaming.py` (`run_streaming_validation`) |
| Dataset fetcher | `src/seerflow/lanl/fetch.py` |
| CSV parser | `src/seerflow/lanl/parser.py` |
| `validate` CLI | `src/seerflow/validate_cmd.py` |
| `benchmark` / scorecard CLI | `src/seerflow/benchmark_cmd.py`, `src/seerflow/launch/benchmark.py` |
| Synthetic fixtures | `tests/fixtures/lanl/` |
| Wiring regression guard | `tests/integration/test_lanl_full_stack_regression.py` |
| Determinism guard | `tests/integration/test_lanl_harness_determinism.py` |
| Design rationale (gaps G1–G5, FR-069–082) | `docs/seerflow-functional-review-2026-05-18.md` |
| Dataset source | <https://csr.lanl.gov/data/cyber1/> |
