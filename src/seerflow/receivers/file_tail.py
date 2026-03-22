"""File tailing receiver — watches log files via watchfiles (Rust inotify).

Supports glob patterns, log rotation detection (inode change + truncation),
offset checkpoint persistence (JSON with atomic write), and restart recovery.

NOT thread-safe — create one instance per event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import glob as glob_module
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import watchfiles

from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from seerflow.receivers.manager import ReceiverManager

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
    """Load file offsets from JSON. Returns empty dict if file is missing or corrupted."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            _log.warning("Checkpoint malformed (not a dict), starting fresh: %s", path)
            return {}
        result: dict[str, FileOffset] = {}
        for k, v in raw.items():
            if not isinstance(v, dict):
                continue
            offset = v.get("offset")
            inode = v.get("inode")
            if not isinstance(offset, int) or not isinstance(inode, int):
                continue
            if offset < 0 or inode < 0:
                continue
            result[k] = FileOffset(offset=offset, inode=inode)
        return result
    except (json.JSONDecodeError, TypeError) as exc:
        _log.warning("Corrupted checkpoint %s, starting fresh: %s", path, exc)
        return {}


def _validate_pattern(pattern: str) -> None:
    """Reject glob patterns containing parent traversal (``..``) components.

    Raises:
        ValueError: If any path component is ``..``.
    """
    parts = Path(pattern).parts
    if ".." in parts:
        msg = f"Pattern contains parent traversal (..): {pattern!r}"
        raise ValueError(msg)


def _is_path_allowed(resolved: str, allowed_roots: tuple[str, ...]) -> bool:
    """Check whether *resolved* path is under at least one allowed root.

    Returns ``True`` if *allowed_roots* is empty (no restriction) or the
    resolved path starts with one of the allowed root directories.
    """
    if not allowed_roots:
        return True
    resolved_path = Path(resolved)
    return any(resolved_path.is_relative_to(Path(root).resolve()) for root in allowed_roots)


_MAX_BYTES_PER_READ = 64 * 1024  # 64 KB per call to bound memory usage


def _read_new_lines(path: Path, offset: int) -> tuple[list[bytes], int]:
    """Read new complete lines from *path* starting at *offset*.

    Returns only complete lines (ending with ``\\n``). Partial lines at
    EOF are left for the next read. Uses a byte-size hint to bound
    memory usage per call.
    """
    with path.open("rb") as fh:
        fh.seek(offset)
        raw_lines = fh.readlines(_MAX_BYTES_PER_READ)
    # Filter out incomplete trailing line (no newline at end)
    complete = [ln for ln in raw_lines if ln.endswith(b"\n")]
    new_offset = offset + sum(len(ln) for ln in complete)
    return complete, new_offset


def _check_rotation(path: Path, saved: FileOffset) -> str:
    """Detect log rotation or truncation.

    Returns one of: ``"ok"``, ``"rotated"``, ``"truncated"``, ``"deleted"``.
    """
    if not path.exists():
        return "deleted"
    stat = path.stat()
    if stat.st_ino != saved.inode:
        return "rotated"
    if saved.offset > stat.st_size:
        return "truncated"
    return "ok"


class FileTailReceiver:
    """Tail log files using watchfiles (Rust inotify) and emit RawEvents.

    Supports glob patterns for file discovery, inode-based rotation detection,
    truncation handling, and JSON checkpoint persistence for restart recovery.
    """

    __slots__ = (
        "_allowed_log_roots",
        "_checkpoint_dir",
        "_checkpoint_path",
        "_debounce_ms",
        "_encoding",
        "_file_paths",
        "_manager",
        "_offsets",
        "_ready",
        "_source_id",
        "_started",
        "_watched_files",
        "_watcher_task",
    )

    def __init__(
        self,
        manager: ReceiverManager,
        *,
        source_id: str,
        file_paths: tuple[str, ...],
        checkpoint_dir: str = "",
        encoding: str = "utf-8",
        debounce_ms: int = 1600,
        allowed_log_roots: tuple[str, ...] = (),
    ) -> None:
        self._manager = manager
        self._source_id = source_id
        self._file_paths = file_paths
        self._checkpoint_dir = checkpoint_dir
        self._encoding = encoding
        self._debounce_ms = debounce_ms
        self._allowed_log_roots = allowed_log_roots
        self._offsets: dict[str, FileOffset] = {}
        self._ready: asyncio.Event = asyncio.Event()
        self._started = False
        self._watcher_task: asyncio.Task[None] | None = None
        self._watched_files: set[str] = set()
        self._checkpoint_path: Path | None = (
            Path(checkpoint_dir) / "file_offsets.json" if checkpoint_dir else None
        )

    async def start(self) -> None:
        """Expand globs, load checkpoints, and start the watcher task."""
        if self._started:
            return
        if self._checkpoint_path:
            self._offsets = _load_checkpoint(self._checkpoint_path)
        for pattern in self._file_paths:
            _validate_pattern(pattern)
            for match in glob_module.glob(pattern, recursive=True):
                p = Path(match)
                if p.is_symlink():
                    _log.warning("Skipping symlink %s — symlinks are not followed", p)
                    continue
                if p.is_file():
                    path_str = str(p.resolve())
                    if not _is_path_allowed(path_str, self._allowed_log_roots):
                        _log.warning("Skipping %s — not under any allowed log root", path_str)
                        continue
                    self._watched_files.add(path_str)
                    if path_str not in self._offsets:
                        stat = p.stat()
                        self._offsets[path_str] = FileOffset(
                            offset=stat.st_size, inode=stat.st_ino
                        )
        self._started = True
        self._watcher_task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        """Cancel the watcher task and persist checkpoints."""
        self._started = False
        if self._watcher_task:
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task
            self._watcher_task = None
        if self._checkpoint_path:
            _save_checkpoint(self._checkpoint_path, self._offsets)

    def is_healthy(self) -> bool:
        """Return True if the receiver has started and not been stopped."""
        return self._started

    async def wait_ready(self, timeout: float = 5.0) -> None:
        """Wait until the watcher loop is actively watching (useful in tests)."""
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    async def _watch_loop(self) -> None:
        """Watch parent directories for file changes and process them."""
        watch_dirs: set[str] = set()
        for fp in self._watched_files:
            watch_dirs.add(str(Path(fp).parent))
        if not watch_dirs:
            self._ready.set()
            return
        self._ready.set()
        try:
            async for changes in watchfiles.awatch(
                *watch_dirs,
                watch_filter=None,
                debounce=self._debounce_ms,
            ):
                if not self._started:
                    break
                modified_paths: set[str] = set()
                for _change_type, change_path in changes:
                    resolved = str(Path(change_path).resolve())
                    if resolved in self._watched_files:
                        modified_paths.add(resolved)
                for path_str in modified_paths:
                    try:
                        await self._process_file(path_str)
                    except OSError as exc:
                        _log.warning("IO error processing %s: %s", path_str, exc)
        except asyncio.CancelledError:
            return

    async def _process_file(self, path_str: str) -> None:
        """Read new lines from a modified file and enqueue as RawEvents."""
        path = Path(path_str)
        saved = self._offsets.get(path_str, FileOffset(offset=0, inode=0))
        status = _check_rotation(path, saved)
        if status == "deleted":
            _log.warning("File deleted: %s", path_str)
            self._watched_files.discard(path_str)
            return
        # Single stat call to avoid TOCTOU races
        st = path.stat()
        if status in ("rotated", "truncated"):
            _log.info("File %s: %s — resetting offset to 0", status, path_str)
            saved = FileOffset(offset=0, inode=st.st_ino)
        lines, new_offset = _read_new_lines(path, saved.offset)
        self._offsets[path_str] = FileOffset(offset=new_offset, inode=st.st_ino)
        for line in lines:
            raw = RawEvent(
                data=line.rstrip(b"\r\n"),
                source_type="file",
                source_id=self._source_id,
                received_ns=time.time_ns(),
                metadata={"path": path_str},
            )
            await self._manager.put_event(raw)
