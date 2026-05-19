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
import time as _time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

import msgspec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from pathlib import Path

    from seerflow.lanl.parser import (
        AnyRecord,
        AuthRecord,
        DnsRecord,
        FlowRecord,
        ProcRecord,
        RedTeamRecord,
    )
    from seerflow.lanl.validator import ValidationResult
    from seerflow.models.alert import Alert
    from seerflow.pipeline.assembly import AssembledHandler
    from seerflow.receivers.base import RawEvent
    from seerflow.storage.factory import StorageBackend

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


def _decode_cursor(blob: bytes | None) -> StreamCursor | None:
    """Decode a cursor; absent (``None``) or corrupt payload → ``None``
    (start fresh)."""
    if blob is None:
        return None
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
    return f"authentication failure for {dst_user} from {rec.src_computer} via {rec.auth_type}"


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
        f"flow established {dst_ip}:{rec.dst_port} from {src_ip}:{rec.src_port} {rec.byte_count}B"
    )


def _dns_message(rec: DnsRecord) -> str:
    """Render a DNS lookup as a detection-attributable beacon message.

    Byte-identical to ``converter.convert_dns_record``'s message (S-315
    AC4 parity). The *resolving* host (``src_computer``) is rendered as its
    deterministic IP so the event attributes to an ``ip`` entity that the
    built-in c2-beaconing rule (and red-team ground-truth matching) keys on;
    ``resolved_computer`` is kept verbatim (incl. the LANL ``?`` marker).
    """
    from seerflow.lanl.hostmap import host_to_ip

    src_ip = host_to_ip(rec.src_computer)
    return (
        f"established dns beacon to {rec.resolved_computer} "
        f"from {src_ip} resolved {rec.resolved_computer}"
    )


_SOURCE_BY_TYPE: dict[str, str] = {
    "AuthRecord": "lanl-auth",
    "ProcRecord": "lanl-proc",
    "FlowRecord": "lanl-flow",
    "DnsRecord": "lanl-dns",
}

# Maps a ``RawEvent.source_id`` (kept byte-identical to
# ``validator._build_raw_events`` — note ``lanl-flow`` is singular) to the
# canonical per-source cursor name used by ``_SOURCE_FILES`` /
# ``StreamCursor.positions`` (``flows`` is plural there). Decoupling these
# two namespaces here keeps message parity intact while making the resume
# islice-skip key-correct.
_CURSOR_NAME_BY_SOURCE_ID: dict[str, str] = {
    "lanl-auth": "auth",
    "lanl-proc": "proc",
    "lanl-flow": "flows",
    "lanl-dns": "dns",
}


def _record_to_raw(rec: AnyRecord, offset_ns: int) -> RawEvent:
    """Build the rebased textual ``RawEvent`` for one merged record."""
    from seerflow.lanl.parser import AuthRecord, DnsRecord, FlowRecord, ProcRecord
    from seerflow.receivers.base import RawEvent

    if isinstance(rec, AuthRecord):
        msg = _auth_message(rec)
    elif isinstance(rec, ProcRecord):
        msg = _proc_message(rec)
    elif isinstance(rec, FlowRecord):
        msg = _flow_message(rec)
    elif isinstance(rec, DnsRecord):
        msg = _dns_message(rec)
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


@dataclass(frozen=True, slots=True)
class StreamingValidationResult:
    """:class:`~seerflow.lanl.validator.ValidationResult` fields plus
    streaming throughput/latency (AC7).

    Reuses ``compute_metrics`` for the accuracy fields so the metric
    semantics are identical to S-305. Attribute access transparently
    delegates to the wrapped result, so callers use ``r.precision`` /
    ``r.per_family`` / ``r.total_events_processed`` directly.
    """

    base: ValidationResult
    throughput_events_per_s: float
    mean_event_latency_s: float

    def __getattr__(self, name: str) -> object:
        # Only reached for names not defined on this dataclass (base /
        # throughput / latency resolve normally) — pass through to the
        # wrapped ValidationResult for precision/recall/per_family/etc.
        return getattr(self.base, name)


def _first_record_time_ns(dataset_dir: Path) -> int:
    """``min_ts`` in ns of the merged stream (first merged record's time)."""
    first = next(_merged_records(_open_sources(dataset_dir, None)), None)
    return 0 if first is None else first.time * 1_000_000_000


async def _persist_cursor(
    storage: StorageBackend, processed: int, offset_ns: int, counts: dict[str, int]
) -> None:
    cursor = StreamCursor(
        events_processed=processed,
        offset_ns=offset_ns,
        positions={
            "auth": counts.get("auth", 0),
            "proc": counts.get("proc", 0),
            "flows": counts.get("flows", 0),
            "dns": counts.get("dns", 0),
        },
    )
    await storage.save_state(CURSOR_STATE_KEY, _encode_cursor(cursor))


def _read_redteam(dataset_dir: Path) -> list[RedTeamRecord]:
    """Parse ``redteam.csv`` (ground truth); missing file → empty list."""
    from seerflow.lanl.parser import parse_redteam_line

    rt_path = dataset_dir / "redteam.csv"
    if not rt_path.exists():
        return []
    return [
        parse_redteam_line(ln.strip())
        for ln in rt_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


async def _replay_stream(
    dataset_dir: Path,
    storage: StorageBackend,
    assembled: AssembledHandler,
    *,
    checkpoint_interval: int,
    max_events: int | None,
    resume_cursor: StreamCursor | None,
) -> tuple[int, int | None]:
    """Drive the rebased stream through the handler under the frozen clock,
    checkpointing ``save_all_state`` + the resume cursor periodically.

    Returns ``(segment_events_processed, offset_ns)``.
    """
    from seerflow.lanl import validator

    processed = 0  # events processed in THIS segment (drives throughput)
    # Cumulative consumed prefix (carried across resumes via the cursor).
    consumed = resume_cursor.events_processed if resume_cursor else 0
    offset_ns: int | None = resume_cursor.offset_ns if resume_cursor else None
    counts: dict[str, int] = dict(resume_cursor.positions) if resume_cursor else {}
    with validator._frozen_replay_clock(validator.REPLAY_EPOCH_NS):
        async for raw in stream_raw_events(dataset_dir, resume_cursor=resume_cursor):
            await assembled.handler(raw)
            processed += 1
            consumed += 1
            src = _CURSOR_NAME_BY_SOURCE_ID[raw.source_id]
            counts[src] = counts.get(src, 0) + 1
            if offset_ns is None:
                offset_ns = raw.received_ns - _first_record_time_ns(dataset_dir)
            if processed % checkpoint_interval == 0:
                await assembled.engines.ensemble.save_all_state(storage)
                await _persist_cursor(storage, consumed, offset_ns, counts)
            if max_events is not None and processed >= max_events:
                break
    await assembled.engines.ensemble.save_all_state(storage)
    if offset_ns is not None:
        await _persist_cursor(storage, consumed, offset_ns, counts)
    return processed, offset_ns


def _score(
    alerts: list[Alert],
    redteam: list[RedTeamRecord],
    offset_ns: int | None,
    processed: int,
) -> ValidationResult:
    """Rebase ground truth by the same constant offset, match, and compute
    combined + per-family metrics (reusing S-305's ``compute_metrics``)."""
    from seerflow.lanl import validator
    from seerflow.lanl.parser import RedTeamRecord

    base_off_s = (offset_ns or 0) // 1_000_000_000
    rebased_rt = [
        RedTeamRecord(
            time=r.time + base_off_s,
            user=r.user,
            src_computer=r.src_computer,
            dst_computer=r.dst_computer,
        )
        for r in redteam
    ]
    tp, fp, missed = validator.match_against_ground_truth(alerts, rebased_rt, time_window_s=300)
    return validator.compute_metrics(
        tp_alerts=tp,
        fp_alerts=fp,
        missed_redteam=missed,
        alerts=alerts,
        events_processed=processed,
        detection_latencies={},
    )


async def _drive(
    dataset_dir: Path,
    storage: StorageBackend,
    *,
    checkpoint_interval: int,
    max_events: int | None,
    resume_cursor: StreamCursor | None,
) -> StreamingValidationResult:
    """Shared replay engine for fresh + resumed runs.

    Drives the streamed LANL events through the full ``assemble_handler``
    stack under S-305's inherited deterministic frozen replay clock,
    checkpointing ``ensemble.save_all_state`` + a resume cursor every
    ``checkpoint_interval`` events, then scores per-family + combined with
    throughput/latency. Alerts are read back from the (caller-owned)
    storage so a resumed run scores the full persisted prefix.
    """
    from seerflow.config import SeerflowConfig
    from seerflow.models.query import AlertQuery
    from seerflow.pipeline.assembly import assemble_handler

    redteam = _read_redteam(dataset_dir)
    assembled = await assemble_handler(SeerflowConfig(), storage)
    t0 = _time.perf_counter()
    try:
        processed, offset_ns = await _replay_stream(
            dataset_dir,
            storage,
            assembled,
            checkpoint_interval=checkpoint_interval,
            max_events=max_events,
            resume_cursor=resume_cursor,
        )
    finally:
        await assembled.teardown()
    elapsed = max(_time.perf_counter() - t0, 1e-9)
    await storage.flush()
    page = await storage.query_alerts(AlertQuery(limit=10_000))
    base = _score(list(page.items), redteam, offset_ns, processed)
    return StreamingValidationResult(
        base=base,
        throughput_events_per_s=processed / elapsed if processed else 0.0,
        mean_event_latency_s=elapsed / processed if processed else 0.0,
    )


async def run_streaming_validation_async(
    dataset_dir: Path,
    *,
    checkpoint_interval: int = 10_000,
    max_events: int | None = None,
) -> StreamingValidationResult:
    """Bounded-memory streaming LANL validation over a fresh temp SQLite DB.

    Convenience surface mirroring :func:`validator.run_validation_async`.
    For a resumable run whose storage survives a process kill use
    :func:`resume_streaming_validation_async` with a caller-owned backend.
    """
    import tempfile

    from seerflow.config import StorageConfig
    from seerflow.storage import connect_storage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = await connect_storage(
            StorageConfig(backend="sqlite", sqlite_path=f"{tmpdir}/lanl.db")
        )
        try:
            return await _drive(
                dataset_dir,
                storage,
                checkpoint_interval=checkpoint_interval,
                max_events=max_events,
                resume_cursor=None,
            )
        finally:
            await storage.close()


async def resume_streaming_validation_async(
    dataset_dir: Path,
    storage: StorageBackend,
    *,
    checkpoint_interval: int = 10_000,
    max_events: int | None = None,
) -> StreamingValidationResult:
    """Resumable surface: load any persisted cursor from ``storage`` and
    continue; if none, run from the start.

    The caller owns ``storage`` (so it survives a process kill, unlike the
    temp-DB :func:`run_streaming_validation_async` convenience wrapper).
    """
    cursor = _decode_cursor(await storage.load_state(CURSOR_STATE_KEY))
    return await _drive(
        dataset_dir,
        storage,
        checkpoint_interval=checkpoint_interval,
        max_events=max_events,
        resume_cursor=cursor,
    )


def run_streaming_validation(
    dataset_dir: Path,
    *,
    checkpoint_interval: int = 10_000,
    max_events: int | None = None,
) -> StreamingValidationResult:
    """Synchronous wrapper (mirrors :func:`validator.run_validation`)."""
    import asyncio

    return asyncio.run(
        run_streaming_validation_async(
            dataset_dir,
            checkpoint_interval=checkpoint_interval,
            max_events=max_events,
        )
    )
