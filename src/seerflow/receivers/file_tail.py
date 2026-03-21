"""File tailing receiver — watches log files via watchfiles (Rust inotify).

Supports glob patterns, log rotation detection (inode change + truncation),
offset checkpoint persistence (JSON with atomic write), and restart recovery.

NOT thread-safe — create one instance per event loop.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FileOffset:
    """Immutable byte-offset + inode pair for a single watched file."""

    offset: int
    inode: int


def _save_checkpoint(path: Path, offsets: dict[str, FileOffset]) -> None:
    """Persist file offsets to JSON with atomic write (tmp + rename)."""
    data = {k: {"offset": v.offset, "inode": v.inode} for k, v in offsets.items()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _load_checkpoint(path: Path) -> dict[str, FileOffset]:
    """Load file offsets from JSON. Returns empty dict if file is missing."""
    if not path.exists():
        return {}
    data: dict[str, dict[str, int]] = json.loads(path.read_text())
    return {k: FileOffset(offset=v["offset"], inode=v["inode"]) for k, v in data.items()}
