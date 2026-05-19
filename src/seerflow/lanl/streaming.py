"""Streaming-scale LANL ingest: bounded-memory, resumable, time-ordered
k-way merge of the LANL source logs into rebased ``RawEvent``\\ s, driven
through the full ``assemble_handler`` detection stack (S-309 / FR-077 /
NFR-014).

This is an **additive** sibling to :mod:`seerflow.lanl.validator` (S-305):
it never alters the in-memory ``run_validation`` path or its published
numbers. The streaming clock-rebase uses a single constant offset derived
from the FIRST merged record (``REPLAY_EPOCH_NS - min_ts``); combined with
the inherited :func:`seerflow.lanl.validator._frozen_replay_clock` the
metrics stay byte-identical across machines (the S-305 determinism
property is preserved by construction — both rebases are pure additive
offsets, so inter-event deltas are identical under the frozen clock).
"""

from __future__ import annotations

import heapq
import itertools
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Callable, TypeVar

import msgspec

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from seerflow.lanl.parser import AnyRecord, AuthRecord, FlowRecord, ProcRecord
    from seerflow.receivers.base import RawEvent

_log = logging.getLogger("seerflow")

_R = TypeVar("_R")

CURSOR_STATE_KEY = "lanl_stream:cursor"


class StreamCursor(msgspec.Struct, frozen=True):
    """Resume cursor persisted via ``ModelStore.save_state``.

    ``positions`` is the count of source lines already consumed per source
    (line index to skip on resume — robust on text files, no byte-seek
    fragility). ``offset_ns`` is the constant rebase offset; it is restored
    (NOT recomputed) on resume so post-resume timestamps match the pre-kill
    run exactly.
    """

    events_processed: int
    offset_ns: int
    positions: dict[str, int]


def _encode_cursor(cursor: StreamCursor) -> bytes:
    return msgspec.json.encode(cursor)


def _decode_cursor(blob: bytes) -> StreamCursor | None:
    """Decode a cursor; corrupt/invalid payload → ``None`` (start fresh)."""
    try:
        return msgspec.json.decode(blob, type=StreamCursor)
    except (msgspec.DecodeError, msgspec.ValidationError, ValueError):
        _log.warning("Corrupt LANL stream cursor — starting fresh", exc_info=True)
        return None


def _iter_record_source(path: Path, parse_fn: Callable[[str], _R]) -> Iterator[_R]:
    """Yield parsed records one line at a time (never whole-file read).

    Missing file → empty iterator (graceful degradation; an optional
    source such as ``dns.csv`` simply contributes nothing to the merge).
    """
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                yield parse_fn(stripped)


def _merged_records(
    record_iters: list[Iterator[AnyRecord]],
) -> Iterator[AnyRecord]:
    """K-way time-merge: each input iterator is individually ``time``-sorted
    (LANL invariant), so :func:`heapq.merge` keyed on ``.time`` yields a
    single globally ascending stream holding at most one record per source
    in memory (k items, independent of total length). ``heapq.merge`` is
    stable left-to-right for equal keys → deterministic ordering.
    """
    yield from heapq.merge(*record_iters, key=lambda r: r.time)


def _auth_message(rec: AuthRecord) -> str:
    """Byte-identical to validator._build_raw_events auth branch."""
    from seerflow.models.entity import normalize_username

    dst_user, _domain = normalize_username(rec.dst_user)
    if rec.success:
        return f"Accepted password for {dst_user} session opened from {rec.src_computer}"
    return (
        f"authentication failure for {dst_user} from {rec.src_computer} via {rec.auth_type}"
    )


def _proc_message(rec: ProcRecord) -> str:
    """Byte-identical to validator._build_raw_events proc branch."""
    from seerflow.models.entity import normalize_username

    username, _domain = normalize_username(rec.user)
    action = "start" if rec.start_end.lower() == "start" else "end"
    return f"process {action}: {rec.process_name} by {username} on {rec.computer}"


def _flow_message(rec: FlowRecord) -> str:
    """Byte-identical to validator._build_raw_events flow branch."""
    from seerflow.lanl.hostmap import host_to_ip

    src_ip = host_to_ip(rec.src_computer)
    dst_ip = host_to_ip(rec.dst_computer)
    return (
        f"flow established {dst_ip}:{rec.dst_port} from "
        f"{src_ip}:{rec.src_port} {rec.byte_count}B"
    )


_SOURCE_BY_TYPE: dict[str, str] = {
    "AuthRecord": "lanl-auth",
    "ProcRecord": "lanl-proc",
    "FlowRecord": "lanl-flow",
}


def _record_to_raw(rec: AnyRecord, offset_ns: int) -> RawEvent:
    """Build the rebased textual ``RawEvent`` for one merged record."""
    from seerflow.lanl.parser import AuthRecord, FlowRecord, ProcRecord
    from seerflow.receivers.base import RawEvent

    if isinstance(rec, AuthRecord):
        msg = _auth_message(rec)
    elif isinstance(rec, ProcRecord):
        msg = _proc_message(rec)
    elif isinstance(rec, FlowRecord):
        msg = _flow_message(rec)
    else:  # pragma: no cover - RedTeamRecord never enters the RawEvent stream
        raise TypeError(f"unsupported record type: {type(rec).__name__}")
    return RawEvent(
        data=msg.encode("utf-8"),
        source_type="syslog",
        source_id=_SOURCE_BY_TYPE[type(rec).__name__],
        received_ns=rec.time * 1_000_000_000 + offset_ns,
        metadata={},
    )


_SOURCE_FILES: tuple[tuple[str, str, str], ...] = (
    ("auth", "auth.csv", "parse_auth_line"),
    ("proc", "proc.csv", "parse_proc_line"),
    ("flows", "flows.csv", "parse_flow_line"),
    ("dns", "dns.csv", "parse_dns_line"),  # optional; absent parser/file → skipped
)


def _open_sources(
    dataset_dir: Path, positions: dict[str, int] | None
) -> list[Iterator[AnyRecord]]:
    """Build per-source line-lazy record iterators, ``islice``-skipping any
    already-consumed prefix on resume.

    ``dns`` is skipped unless its parser exists (FR-081 is a later story) —
    keeps the merge source-count agnostic without implementing DNS here.
    """
    from seerflow.lanl import parser as _parser

    iters: list[Iterator[AnyRecord]] = []
    for name, filename, parse_attr in _SOURCE_FILES:
        parse_fn = getattr(_parser, parse_attr, None)
        if parse_fn is None:
            continue
        src: Iterator[AnyRecord] = _iter_record_source(dataset_dir / filename, parse_fn)
        skip = (positions or {}).get(name, 0)
        if skip:
            src = itertools.islice(src, skip, None)
        iters.append(src)
    return iters


async def stream_raw_events(
    dataset_dir: Path,
    *,
    resume_cursor: StreamCursor | None = None,
) -> AsyncIterator[RawEvent]:
    """Pull-based async iterator of rebased textual ``RawEvent``\\ s.

    The rebase offset is a single constant: on a fresh run it is
    ``REPLAY_EPOCH_NS - first_merged_record.time * 1e9`` (the first merged
    record carries ``min_ts`` because every source is ``time``-ascending);
    on resume it is taken verbatim from ``resume_cursor.offset_ns`` (NOT
    recomputed) so post-resume timestamps match the pre-kill run exactly.
    Memory is O(#sources): no list/sort/read_text over the dataset.
    """
    from seerflow.lanl import validator

    positions = resume_cursor.positions if resume_cursor is not None else None
    merged = _merged_records(_open_sources(dataset_dir, positions))

    if resume_cursor is not None:
        offset_ns = resume_cursor.offset_ns
    else:
        first = next(merged, None)
        if first is None:
            return
        offset_ns = validator.REPLAY_EPOCH_NS - first.time * 1_000_000_000
        yield _record_to_raw(first, offset_ns)

    for rec in merged:
        yield _record_to_raw(rec, offset_ns)
