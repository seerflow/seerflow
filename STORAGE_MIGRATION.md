# Storage Backend Migration: SQLite → PostgreSQL

This runbook walks an operator through switching Seerflow's storage backend
from the zero-config SQLite default to PostgreSQL for production scale.

The switch itself is a one-line YAML change. Replaying historical events
into the new backend is operator-driven — Seerflow does **not** automatically
copy SQLite rows into PostgreSQL, and there is no in-place migration tool in
v1.

## Overview

Seerflow ships two storage backends behind the same Protocol contract:

| Backend     | Use case                                  | Concurrency  | FTS          |
| ----------- | ----------------------------------------- | ------------ | ------------ |
| SQLite      | Default; single-host, < ~10K events/sec   | Single-writer + WAL | FTS5    |
| PostgreSQL  | Production; multi-reader, ≥ 10K events/sec | Pooled async (asyncpg) | `tsvector` + GIN |

Application code (pipeline, API, CLI) depends only on the storage Protocol
interfaces (`LogStore`, `AlertStore`, `ModelStore`, `EntityStore`, `GraphStore`,
`SigmaRuleStateStore`). Switching backends is a config-layer change — no
code change, no redeploy of compiled artefacts.

The migration covers:

1. Installing the `postgres` optional extra.
2. Provisioning a PostgreSQL database.
3. Updating `seerflow.yaml`.
4. Restarting Seerflow.
5. (Optional) Replaying historical events from the SQLite snapshot via
   `seerflow import`.
6. Validating the cut-over.
7. Rolling back if needed.

## Prerequisites

- **PostgreSQL ≥ 14**, reachable from the Seerflow host (network + auth).
- The `postgres` optional extra installed:
  ```bash
  uv sync --extra postgres
  ```
  This pulls in `asyncpg` and (for tests) `testcontainers`.
- A pre-created PostgreSQL database the Seerflow user can connect to.
  Seerflow auto-creates its tables on first connect; it does **not** create
  the database itself.
- A backup of the current SQLite database (`seerflow.db` under your
  `data_dir`). Copy it somewhere outside the data directory in case you
  need to roll back.

## Migration Procedure

1. **Stop the Seerflow process.** A clean shutdown flushes pending writes
   to SQLite. If you have systemd: `systemctl stop seerflow`. If you launched
   it manually, send SIGTERM and wait for the process to exit.

2. **Provision PostgreSQL.** Create a database and a user with the required
   privileges:
   ```sql
   CREATE DATABASE seerflow;
   CREATE USER seerflow WITH PASSWORD '...';
   GRANT ALL PRIVILEGES ON DATABASE seerflow TO seerflow;
   ```
   Set the DSN in your environment so secrets never land in YAML:
   ```bash
   export SEERFLOW_PG_URL="postgresql://seerflow:...@db.host:5432/seerflow"
   ```

3. **Edit `seerflow.yaml`.** Switch the `storage.backend` field and add the
   URL plus any pool tuning:
   ```yaml
   storage:
     backend: postgresql
     postgresql_url: ${SEERFLOW_PG_URL}
     postgresql_pool_min_size: 2       # default; tune for your concurrency
     postgresql_pool_max_size: 10      # default; raise for high-traffic dashboards
     postgresql_command_timeout_s: 30  # default; raise for very large queries
   ```
   The example file (`seerflow.example.yaml`) ships with both backends
   documented side-by-side.

4. **Start Seerflow.** First boot will auto-create the schema (migrations
   v1 through v6) and the FTS index. The startup log lines that confirm
   the cut-over are roughly:
   ```
   storage.backend=postgresql pool=asyncpg(min=2,max=10) timeout_s=30.0
   migrations.applied total=6 newest=6
   storage.ready backend=postgresql
   ```
   If the operator forgot to set `postgresql_url`, the new DSN-required
   check (S-074) surfaces a clear `ConfigError` at config-load time rather
   than at connect time.

5. **(Optional) Replay historical events.** If you need the events that
   were written to the SQLite snapshot before the switch, use the existing
   `seerflow import` CLI:
   ```bash
   # Export from SQLite snapshot (read-only access; safe with WAL).
   sqlite3 /backup/seerflow.db "SELECT data FROM events" --json > events.json
   # Replay into PostgreSQL via the running Seerflow instance.
   uv run python -m seerflow import events.json
   ```
   This is opt-in. Seerflow does not automatically copy rows — see the
   FAQ below for why.

## Validation

After the cut-over completes, verify that writes and reads are landing on
PostgreSQL:

- **Logs.** Look for `storage.backend=postgresql` and `storage.ready` lines.
- **Counter.** `select count(*) from events;` in PostgreSQL grows as new
  events flow through ingestion.
- **Dashboard.** The API surface (event count, alert feed) reflects the
  new backend immediately; concurrent reads no longer block writes.
- **Health endpoint.** Once `seerflow status` lands (S-075), `seerflow status`
  prints the active backend and pool metrics. Until then, the API `/health`
  endpoint plus the startup log are the authoritative signal.

## Rollback

If something goes wrong, rolling back is symmetric:

1. Stop Seerflow.
2. Flip `storage.backend` back to `sqlite` in `seerflow.yaml`. Leave the
   `postgresql_*` knobs in place — they are inert when backend is SQLite.
3. Start Seerflow. It re-attaches to the SQLite snapshot.

Trade-off: events written to PostgreSQL after the cut-over are **not**
automatically copied back to SQLite. If you need them in the SQLite file,
export from PostgreSQL and replay via `seerflow import`, the same way as
the forward direction.

## FAQ

**Do my old SQLite rows automatically copy?** No. The migration is at the
config layer — the application stops talking to SQLite and starts talking
to PostgreSQL on the next start. Historical data is preserved in the SQLite
file on disk, but the running pipeline does not see it after the switch.
Use `seerflow import` to replay it if you need it in the new backend.

**Can I run both backends in parallel?** No. Seerflow is single-backend per
process; the factory dispatches once at startup and the pipeline holds a
single backend reference. Running two instances against the same source
will produce duplicate events, not a dual-write layer.

**What about graph data and entity state?** The entity graph and the
correlation engine state are rebuilt as events flow into the new backend.
ML model state is persisted in the storage layer (`ModelStore`) and is
**not** auto-copied either — set models will warm up on the new backend.

**Do I need to run migrations manually?** No. Both backends auto-create
their schema and run any pending migrations on the first connect. The same
migration version numbers (1 through 6) apply to both — Seerflow does not
mix schemas.

**What if I want zero-downtime?** Not supported in v1. Stop, switch, start
is the supported pattern. Live cutover and dual-write are tracked as a
future production-hardening story (Sprint 14).

**Where do I find connection-pool tuning guidance?** Start with the defaults
(min=2, max=10, timeout=30s). Raise `pool_max_size` if the dashboard shows
queueing latency under load; raise `command_timeout_s` if very large
`query_events` calls time out. The pool knobs validate at config-load
time — invalid values produce a clear `ConfigError` before Seerflow tries
to connect.
