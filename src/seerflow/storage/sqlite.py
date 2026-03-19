"""SQLite storage backend — schema creation and event batch writes.

Implements ``LogStore.write_events`` via aiosqlite with WAL mode.
Schema is auto-created on first run. Events are batched via ``WriteBuffer``
(1000 events or 100ms, whichever first) for high-throughput writes.

See: docs/superpowers/specs/2026-03-18-s006-sqlite-backend-design.md
"""

from __future__ import annotations
