"""Batch log import — file reading, glob expansion, and import pipeline."""

from __future__ import annotations

import bz2
import glob as _glob
import gzip
import logging
import lzma
import time
from pathlib import Path
from typing import IO

_log = logging.getLogger("seerflow")

_BINARY_CHECK_SIZE = 8192
_COMPRESSED_SUFFIXES = frozenset({".gz", ".bz2", ".xz", ".lzma"})


def open_log(path: Path) -> IO[str]:
    """Open a log file for reading, auto-detecting compression.

    Supports: .gz (gzip), .bz2 (bzip2), .xz/.lzma (lzma).
    All other extensions open as plain text with UTF-8 + replace errors.
    """
    suffix = path.suffix.lower()
    if suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    if suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", errors="replace")
    if suffix in (".xz", ".lzma"):
        return lzma.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def is_binary(path: Path) -> bool:
    """Check if a file is binary by looking for null bytes in the first 8KB.

    Compressed files (.gz, .bz2, .xz, .lzma, .zst) are never considered binary
    since their raw content is binary but decompressed content is text.
    """
    if path.suffix.lower() in _COMPRESSED_SUFFIXES:
        return False
    try:
        chunk = path.read_bytes()[:_BINARY_CHECK_SIZE]
        return b"\x00" in chunk
    except OSError as exc:
        _log.warning("Could not read %s for binary check: %s", path, exc)
        return False


def expand_paths(patterns: list[str]) -> list[Path]:
    """Expand glob patterns to a deduplicated list of file paths.

    Skips directories and non-existent paths with warnings.
    """
    seen: set[Path] = set()
    result: list[Path] = []
    for pattern in patterns:
        matches = sorted(Path(m) for m in _glob.glob(pattern, recursive=True))
        if not matches:
            _log.warning("No files matched pattern: %s", pattern)
            continue
        for path in matches:
            if path.is_dir():
                continue
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)
    return result


async def run_import(
    *,
    paths: list[str],
    db_path: str,
) -> dict[str, int | float]:
    """Import log files through the Seerflow pipeline.

    Returns stats: files_processed, lines_read, lines_read, elapsed_seconds.
    """
    from seerflow.config import StorageConfig, load_config
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.pipeline.handler import make_handler
    from seerflow.receivers.base import RawEvent
    from seerflow.storage.sqlite import SqliteBackend

    start = time.monotonic()
    expanded = expand_paths(paths)

    if not expanded:
        return {
            "files_processed": 0,
            "lines_read": 0,
            "elapsed_seconds": 0.0,
        }

    # Minimal pipeline setup — no sigma, no graph, no correlation
    config = load_config()
    storage_config = StorageConfig(
        backend="sqlite",
        data_dir=str(Path(db_path).parent),
        sqlite_path=db_path,
    )
    storage = await SqliteBackend.connect(storage_config)

    try:
        ensemble = DetectionEnsemble(config.detection)
        handler = make_handler(ensemble, storage)

        files_processed = 0
        lines_read = 0

        for file_path in expanded:
            if is_binary(file_path):
                _log.warning("Skipping binary file: %s", file_path)
                continue

            _log.info("Importing: %s", file_path)
            file_lines = 0
            try:
                with open_log(file_path) as fh:
                    for line in fh:
                        line = line.rstrip("\n\r")
                        if not line:
                            continue
                        raw = RawEvent(
                            data=line.encode("utf-8"),
                            source_type="import",
                            source_id=str(file_path),
                            received_ns=time.time_ns(),
                            metadata={},
                        )
                        await handler(raw)
                        file_lines += 1
            except OSError as exc:
                _log.warning("Skipping unreadable file %s: %s", file_path, exc)
                continue

            lines_read += file_lines
            files_processed += 1
            _log.info("  %s: %d lines", file_path.name, file_lines)

        elapsed = time.monotonic() - start
        _log.info(
            "Import complete: %d files, %d lines in %.1fs",
            files_processed,
            lines_read,
            elapsed,
        )
        return {
            "files_processed": files_processed,
            "lines_read": lines_read,
            "elapsed_seconds": round(elapsed, 2),
        }
    finally:
        await storage.close()
