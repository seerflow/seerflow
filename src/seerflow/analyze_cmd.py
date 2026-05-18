"""CLI handler for ``seerflow analyze`` (S-303, FR-070).

One-shot full-stack batch: drive ``pipeline.assembly.assemble_handler``
(S-302) over a finite file/glob/stdin source, then emit the scored alerts
written during the run as NDJSON. ``seerflow import`` (the fast ML-only
path) is deliberately untouched (OQ-3 resolved: new command).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from seerflow.import_cmd import expand_paths, is_binary, open_log

if TYPE_CHECKING:
    from collections.abc import Iterator

    from seerflow.config import SeerflowConfig
    from seerflow.config import StorageConfig as _StorageConfigT
    from seerflow.receivers.base import RawEvent
    from seerflow.storage.factory import StorageBackend

_log = logging.getLogger("seerflow")

_ALERT_PAGE_SIZE = 1000
"""Page size for the post-run alert query. Mirrors export_cmd."""


def _iter_raw_events(paths: list[str], *, stdin: TextIO) -> Iterator[RawEvent]:
    """Yield ``RawEvent``s from expanded file paths and/or stdin.

    A ``-`` token reads newline-delimited lines from ``stdin``. File paths
    are glob-expanded; binary and unreadable files are skipped with a
    warning (mirrors ``import_cmd.run_import``). Blank lines are dropped.
    """
    from seerflow.receivers.base import RawEvent

    file_patterns = [p for p in paths if p != "-"]
    has_stdin = any(p == "-" for p in paths)

    for file_path in expand_paths(file_patterns):
        if is_binary(file_path):
            _log.warning("Skipping binary file: %s", file_path)
            continue
        try:
            with open_log(file_path) as fh:
                for line in fh:
                    text = line.rstrip("\n\r")
                    if not text:
                        continue
                    yield RawEvent(
                        data=text.encode("utf-8"),
                        source_type="analyze",
                        source_id=str(file_path),
                        received_ns=time.time_ns(),
                        metadata={},
                    )
        except OSError as exc:
            _log.warning("Skipping unreadable file %s: %s", file_path, exc)
            continue

    if has_stdin:
        for line in stdin:
            text = line.rstrip("\n\r")
            if not text:
                continue
            yield RawEvent(
                data=text.encode("utf-8"),
                source_type="analyze",
                source_id="-",
                received_ns=time.time_ns(),
                metadata={},
            )


def _storage_config_for(
    config: SeerflowConfig, *, persist: bool, db: str | None
) -> _StorageConfigT:
    """Resolve the storage config for this run.

    ``--no-persist`` (default) → in-memory SQLite (nothing hits disk).
    ``--persist`` → the configured backend, with an optional ``--db``
    sqlite-path override (mirrors ``seerflow import``).
    """
    from seerflow.config import StorageConfig

    if not persist:
        return StorageConfig(backend="sqlite", sqlite_path=":memory:", data_dir="")
    if db is not None:
        return StorageConfig(
            backend="sqlite",
            data_dir=str(Path(db).parent),
            sqlite_path=db,
        )
    return config.storage


async def _emit_alerts_ndjson(
    storage: StorageBackend,
    stream: TextIO,
    run_start_ns: int,
) -> int:
    """Write every alert stored on/after ``run_start_ns`` as NDJSON.

    Pages ``storage.query_alerts`` over a ``[run_start_ns, now]`` window
    (capture-via-query: the handler persists alerts during the run).
    Reuses ``export_cmd._alert_to_json_dict`` for an identical JSON shape.
    Returns the number of alert lines written.
    """
    import msgspec.json

    from seerflow.export_cmd import _alert_to_json_dict
    from seerflow.models.query import AlertQuery, TimeRange

    window = TimeRange(start_ns=run_start_ns, end_ns=time.time_ns())
    emitted = 0
    page = 1
    while True:
        result = await storage.query_alerts(
            AlertQuery(time_range=window, page=page, limit=_ALERT_PAGE_SIZE)
        )
        if not result.items:
            return emitted
        for alert in result.items:
            stream.write(msgspec.json.encode(_alert_to_json_dict(alert)).decode("utf-8"))
            stream.write("\n")
            emitted += 1
        if not result.has_next:
            return emitted
        page += 1
