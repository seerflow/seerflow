# CLI reference

This page documents the flags exposed by the `seerflow` command-line. Every
flag listed below is checked by the
[docs-drift workflow](../../scripts/check_docs_drift.py) against the
`argparse` parser built by `seerflow.cli.build_parser()`; a flag that has
been removed from the parser will fail CI here.

> **Scope of this page.** This is the v1.1 minimum-viable reference covering
> the flags most operators reach for first. Flags not yet documented appear
> as drift-check **warnings** (informational) rather than failures, so the
> reference can grow without churning CI.

## Global

The top-level `seerflow` invocation takes only the universal `--config` and
`--version`/`--help` options. The drift checker intentionally excludes
those three from validation.

## query

`seerflow query events|alerts|templates|timeline|health` — read from the
local store.

* `--last` — time window, e.g. `1h`, `30m`, `7d`.
* `--template` — filter `query events` by Drain3 template ID.
* `--source` — filter by source identifier.
* `--severity` — minimum severity (0-6).
* `--limit` — maximum number of rows returned.
* `--json` — emit JSON instead of the human table.
* `--tactic` — filter `query alerts` by MITRE ATT&CK tactic.
* `--technique` — filter `query alerts` by ATT&CK technique.
* `--type` — filter `query alerts` by alert type.

## export

`seerflow export events|alerts` — bulk-export the store.

* `--from`, `--to` — ISO timestamps bounding the export.
* `--since` — convenience alternative to `--from`.
* `--format` — `ndjson` or `csv`.
* `--output` — output file path.
* `--alerts-to`, `--alerts-format` — alert-specific output target/format.

## import

`seerflow import` — load logs from disk into the store.

* `--batch-size` — rows committed per transaction.
* `--wipe-destination` — clear the destination before importing.
* `--yes` — skip confirmation prompts.
* `--db` — alternate database path.
* `--source` — override the source identifier recorded with each event.
* `--dry-run` — parse but do not write.

## analyze

`seerflow analyze <path|glob|->` — run a file/stdin through the full
detection stack.

* `--persist`, `--no-persist` — whether to write events to the store.
* `--tui` — interactive TUI viewer.
* `--limit` — stop after N events.
* `--seed` — deterministic detector seeding for reproducible runs.

## benchmark

`seerflow benchmark` — measure throughput / latency / RSS.

* `--dataset-dir` — directory of fixture log files.
* `--scorecard` — emit a combined accuracy + performance scorecard.
* `--timeout` — wall-clock limit.
* `--count` — number of synthetic events to push.

## graph

`seerflow graph` — entity graph maintenance.

* `--batch-size` — migration batch size.
* `--min-count` — prune entities below this event count.
* `--note` — free-text annotation on the migration log.

## feedback

`seerflow feedback` — mark an alert as true/false positive.

* `--json` — return the response as JSON.

## Verifying this page

The drift checker (`scripts/check_docs_drift.py`) walks the actual argparse
parser exported by `seerflow.cli.build_parser()` and diffs against the long
flags mentioned in this file. See the
[configuration reference](configuration.md#verifying-this-page) for the
exact invocation — the same command checks both the config and CLI sides.
