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
import stat as stat_module
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

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
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _load_checkpoint(path: Path) -> dict[str, FileOffset]:
    """Load file offsets from JSON. Returns empty dict if file is missing or corrupted."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        _log.warning("Corrupted checkpoint %s, starting fresh: %s", path, exc)
        return {}
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
    return any(resolved_path.is_relative_to(root) for root in allowed_roots)


_MAX_BYTES_PER_READ = 64 * 1024  # 64 KB per call to bound memory usage
_MAX_LINE_BYTES = 1024 * 1024  # 1 MB — lines exceeding this are discarded


def _read_new_lines(path: Path, offset: int) -> tuple[list[bytes], int]:
    """Read new complete lines from *path* starting at *offset*.

    Returns only complete lines (ending with ``\\n``) that are within
    the ``_MAX_LINE_BYTES`` limit. Oversized lines are logged and
    discarded. Partial lines at EOF are left for the next read.
    """
    with path.open("rb") as fh:
        fh.seek(offset)
        raw_lines = fh.readlines(_MAX_BYTES_PER_READ)
    complete: list[bytes] = []
    total_bytes = 0
    for ln in raw_lines:
        if not ln.endswith(b"\n"):
            continue
        total_bytes += len(ln)
        if len(ln) > _MAX_LINE_BYTES:
            _log.warning("Discarding oversized line (%d bytes) from %s", len(ln), path)
            continue
        complete.append(ln)
    new_offset = offset + total_bytes
    return complete, new_offset


RotationStatus = Literal["ok", "rotated", "truncated", "deleted"]


def _check_rotation(stat_result: os.stat_result | None, saved: FileOffset) -> RotationStatus:
    """Detect log rotation or truncation from a pre-fetched stat result.

    Accepts ``None`` when the file no longer exists (deleted).
    The caller is responsible for performing the ``stat()`` call — this
    function never touches the filesystem, eliminating TOCTOU windows.
    """
    if stat_result is None:
        return "deleted"
    if stat_result.st_ino != saved.inode:
        return "rotated"
    if saved.offset > stat_result.st_size:
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
        debounce_ms: int = 1600,
        allowed_log_roots: tuple[str, ...] = (),
    ) -> None:
        if checkpoint_dir:
            cp_parts = Path(checkpoint_dir).parts
            if ".." in cp_parts:
                msg = f"checkpoint_dir must not contain '..': {checkpoint_dir!r}"
                raise ValueError(msg)
        self._manager = manager
        self._source_id = source_id
        self._file_paths = file_paths
        self._checkpoint_dir = checkpoint_dir
        self._debounce_ms = debounce_ms
        self._allowed_log_roots: tuple[str, ...] = tuple(
            str(Path(r).resolve()) for r in allowed_log_roots
        )
        if file_paths and not allowed_log_roots:
            _log.warning(
                "No 'allowed_log_roots' set - file tailing can read any file. "
                "Set allowed_log_roots in seerflow.yaml to restrict to specific directories"
            )
        self._offsets: dict[str, FileOffset] = {}
        self._ready: asyncio.Event = asyncio.Event()
        self._started = False
        self._watcher_task: asyncio.Task[None] | None = None
        self._watched_files: set[str] = set()
        self._checkpoint_path: Path | None = (
            Path(checkpoint_dir) / "file_offsets.json" if checkpoint_dir else None
        )

    def _expand_globs(self) -> set[str]:
        """Expand glob patterns into validated, resolved file paths.

        Skips symlinks and paths outside allowed roots. Initialises offsets
        for newly-discovered files (tail from end). Returns the set of
        *new* paths that were not previously in ``_watched_files``.
        """
        newly_added: set[str] = set()
        for pattern in self._file_paths:
            _validate_pattern(pattern)
            for match in glob_module.glob(pattern, recursive=True):
                p = Path(match)
                try:
                    st = p.lstat()  # single syscall — atomic symlink + file check
                except OSError:
                    _log.debug("Skipping inaccessible path %s", p)
                    continue
                if stat_module.S_ISLNK(st.st_mode):
                    _log.warning("Skipping symlink %s — symlinks are not followed", p)
                    continue
                if not stat_module.S_ISREG(st.st_mode):
                    continue
                path_str = str(p.resolve())
                if path_str in self._watched_files:
                    continue
                if not _is_path_allowed(path_str, self._allowed_log_roots):
                    _log.warning("Skipping %s — not under any allowed log root", path_str)
                    continue
                self._watched_files.add(path_str)
                if path_str not in self._offsets:
                    self._offsets[path_str] = FileOffset(offset=st.st_size, inode=st.st_ino)
                newly_added.add(path_str)
        return newly_added

    async def start(self) -> None:
        """Load checkpoints, expand globs, and start the watcher task."""
        if self._started:
            return
        if self._checkpoint_path:
            self._offsets = _load_checkpoint(self._checkpoint_path)
            if self._allowed_log_roots:
                self._offsets = {
                    k: v
                    for k, v in self._offsets.items()
                    if _is_path_allowed(k, self._allowed_log_roots)
                }
        self._expand_globs()
        if self._watched_files:
            # Verify at least one matched file is readable
            readable = [f for f in self._watched_files if os.access(f, os.R_OK)]
            if not readable:
                unreadable = list(self._watched_files)[:3]
                msg = (
                    f"Found {len(self._watched_files)} file(s) but none are readable "
                    f"(e.g. {unreadable}). Run as root or adjust file permissions."
                )
                raise PermissionError(msg)
            _log.info("Watching %d file(s):", len(readable))
            for f in sorted(readable):
                _log.info("  %s", f)
            if len(readable) < len(self._watched_files):
                skipped = len(self._watched_files) - len(readable)
                _log.warning(
                    "%d of %d matched files are not readable (skipped)",
                    skipped,
                    len(self._watched_files),
                )
        else:
            # No files matched — check if parent dirs are accessible
            any_accessible = False
            for pattern in self._file_paths:
                parent = Path(pattern).parent
                if parent.is_dir() and os.access(str(parent), os.R_OK):
                    any_accessible = True
                    break
            if not any_accessible:
                msg = (
                    f"No readable directories found for patterns {self._file_paths}. "
                    "Check file permissions and allowed_log_roots."
                )
                raise PermissionError(msg)
            _log.warning(
                "No files match patterns %s — watching directories for new files. "
                "Check that the file paths and extensions are correct.",
                self._file_paths,
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
        """Watch parent directories for file changes and process them.

        When a ``Change.added`` event is detected, re-runs glob expansion
        to discover new files (e.g. after log rotation). If any newly
        discovered file lives in a directory not yet being watched, the
        loop restarts ``awatch`` with the updated directory set.
        """
        watch_dirs: set[str] = set()
        for fp in self._watched_files:
            watch_dirs.add(str(Path(fp).parent))
        # When no files match, derive watch dirs from glob pattern parents
        if not watch_dirs:
            for pattern in self._file_paths:
                _validate_pattern(pattern)
                parent = str(Path(pattern).parent.resolve())
                if not os.path.isdir(parent):
                    continue
                if not _is_path_allowed(parent, self._allowed_log_roots):
                    continue
                watch_dirs.add(parent)
        if not watch_dirs:
            _log.warning(
                "No watchable directories found (%d patterns configured)",
                len(self._file_paths),
            )
            self._ready.set()
            return
        self._ready.set()
        try:
            while self._started:
                restart_needed = False
                async for changes in watchfiles.awatch(
                    *watch_dirs,
                    watch_filter=None,
                    debounce=self._debounce_ms,
                    recursive=False,
                    ignore_permission_denied=True,
                ):
                    if not self._started:
                        return
                    # Check whether any change is an "added" event
                    has_added = any(ct == watchfiles.Change.added for ct, _ in changes)
                    new_paths: set[str] = set()
                    if has_added:
                        new_paths = self._expand_globs()
                        for new_path in new_paths:
                            # _expand_globs sets offset=st_size for new files, or
                            # preserves a stale checkpoint offset for re-created files.
                            # Either way, reset to 0 to read the full file on first
                            # detection. _process_file handles inode mismatches.
                            saved = self._offsets[new_path]  # always set by _expand_globs
                            self._offsets[new_path] = FileOffset(offset=0, inode=saved.inode)
                            try:
                                await self._process_file(new_path)
                            except OSError as exc:
                                _log.warning(
                                    "IO error processing new file %s: %s",
                                    new_path,
                                    exc,
                                )
                            parent = str(Path(new_path).parent.resolve())
                            if parent not in watch_dirs:
                                watch_dirs.add(parent)
                                restart_needed = True
                    modified_paths: set[str] = set()
                    for _change_type, change_path in changes:
                        resolved = str(Path(change_path).resolve())
                        if resolved in self._watched_files and resolved not in new_paths:
                            modified_paths.add(resolved)
                    for path_str in modified_paths:
                        try:
                            await self._process_file(path_str)
                        except OSError as exc:
                            _log.warning("IO error processing %s: %s", path_str, exc)
                    if restart_needed:
                        break  # break inner awatch loop to restart with new dirs
        except asyncio.CancelledError:
            return

    async def _process_file(self, path_str: str) -> None:
        """Read new lines from a modified file and enqueue as RawEvents."""
        path = Path(path_str)
        saved = self._offsets.get(path_str, FileOffset(offset=0, inode=0))
        try:
            st = path.stat()
        except OSError:
            _log.warning("File deleted: %s", path_str)
            self._watched_files.discard(path_str)
            return
        status = _check_rotation(st, saved)
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
