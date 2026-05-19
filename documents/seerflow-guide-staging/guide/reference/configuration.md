# Configuration reference

Seerflow loads configuration from a YAML file (`--config seerflow.yaml`) and
falls back to sane defaults when no file is supplied (zero-config startup).
Every key documented below maps directly to a field on
`seerflow.config.SeerflowConfig` and its nested dataclasses; the
[docs-drift CI workflow](../../scripts/check_docs_drift.py) verifies that the
keys listed here still exist in the installed package.

> **Scope of this page.** This is the v1.1 minimum-viable reference, focused
> on the keys most operators actually touch in their first month. The
> drift-check script also tolerates schema fields that are *not* documented
> here — they are reported as warnings, not failures, so this page can grow
> incrementally without breaking CI.

## Storage

```yaml
storage:
  backend: sqlite
  data_dir: ""
  sqlite_path: ""
  graph_backend: igraph
```

* `storage.backend` — `sqlite` (default) or `postgresql`.
* `storage.data_dir` — base directory for SQLite + checkpoint files. Empty string means platform default.
* `storage.sqlite_path` — explicit SQLite file path. Overrides `data_dir`.
* `storage.graph_backend` — entity graph backend; `igraph` (in-process default), `falkordb`, or `postgres_age`.

## Detection

```yaml
detection:
  hst_n_trees: 25
  hst_window_size: 250
  hw_alpha: 0.2
  hw_beta: 0.05
  hw_gamma: 0.1
  hw_n_std: 3.0
  risk_threshold: 0.7
  score_interval: 1.0
```

* `detection.hst_n_trees` — number of Half-Space Trees in the ensemble.
* `detection.hst_window_size` — sliding window size for the HST detector.
* `detection.hw_alpha`, `detection.hw_beta`, `detection.hw_gamma` — Holt-Winters smoothing parameters (level, trend, seasonal).
* `detection.hw_n_std` — alert threshold in standard deviations from the Holt-Winters forecast.
* `detection.risk_threshold` — minimum blended score to emit a risk-accumulation alert.
* `detection.score_interval` — seconds between blended-score evaluations.

## Correlation

```yaml
correlation:
  window_duration_seconds: 300
  late_tolerance_seconds: 60
  max_entities: 100000
  max_events_per_entity: 1000
```

* `correlation.window_duration_seconds` — sliding-window width for entity-temporal joins.
* `correlation.late_tolerance_seconds` — grace period for out-of-order events.
* `correlation.max_entities` — soft cap on retained entities.
* `correlation.max_events_per_entity` — per-entity event history cap.

## Alerting

```yaml
alerting:
  console_enabled: true
  console_stream: stderr
  console_format: human
  console_min_severity: 3
  file_enabled: false
  file_path: ""
  dedup_window_seconds: 300
```

* `alerting.console_enabled` — emit alerts to the console.
* `alerting.console_stream` — `stderr` or `stdout`.
* `alerting.console_format` — `human` or `json`.
* `alerting.console_min_severity` — minimum severity (1-6) for console output.
* `alerting.file_enabled` — also write alerts to a file.
* `alerting.file_path` — file destination when `file_enabled: true`.
* `alerting.dedup_window_seconds` — alert dedup window.

## Top-level (daemon)

```yaml
dashboard_port: 8080
log_level: INFO
shutdown_timeout_s: 5.0
```

* `dashboard_port` — HTTP dashboard port.
* `log_level` — `DEBUG`, `INFO`, `WARNING`, `ERROR`.
* `shutdown_timeout_s` — graceful shutdown deadline.

## Verifying this page

Run the drift checker locally — it should exit zero:

```bash
uv run python scripts/check_docs_drift.py \
  --docs-dir docs \
  --report-path drift-report.json
```

If it exits non-zero with a `config.extra_in_docs` entry, this page documents
a key that no longer exists in the installed `seerflow` package; remove it
or rename it to match the new schema.
