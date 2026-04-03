"""Batch log import — file reading, glob expansion, and import pipeline."""

from __future__ import annotations

import bz2
import glob as _glob
import gzip
import logging
import lzma
from pathlib import Path
from typing import IO

_log = logging.getLogger("seerflow")

_BINARY_CHECK_SIZE = 8192
_COMPRESSED_SUFFIXES = frozenset({".gz", ".bz2", ".xz", ".lzma", ".zst"})


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
    except OSError:
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
