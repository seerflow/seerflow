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
import logging
from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from seerflow.lanl.parser import AnyRecord

_log = logging.getLogger("seerflow")

_R = TypeVar("_R")


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
