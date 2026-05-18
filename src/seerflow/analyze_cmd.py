"""CLI handler for ``seerflow analyze`` (S-303, FR-070).

One-shot full-stack batch: drive ``pipeline.assembly.assemble_handler``
(S-302) over a finite file/glob/stdin source, then emit the scored alerts
written during the run as NDJSON. ``seerflow import`` (the fast ML-only
path) is deliberately untouched (OQ-3 resolved: new command).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, TextIO

from seerflow.import_cmd import expand_paths, is_binary, open_log

if TYPE_CHECKING:
    from collections.abc import Iterator

    from seerflow.receivers.base import RawEvent

_log = logging.getLogger("seerflow")


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
