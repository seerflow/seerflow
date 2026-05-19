"""Unit tests for the streaming-scale LANL ingest (S-309 / FR-077)."""

from __future__ import annotations

import collections.abc
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"


@pytest.fixture
def streaming():
    from seerflow.lanl import streaming as mod

    return mod


def test_iter_record_source_is_lazy_and_parses(streaming, tmp_path):
    from seerflow.lanl.parser import parse_proc_line

    p = tmp_path / "proc.csv"
    p.write_text("10,U1@DOM1,C1,P1,Start\n20,U2@DOM1,C2,P2,End\n", encoding="utf-8")
    it = streaming._iter_record_source(p, parse_proc_line)

    assert isinstance(it, collections.abc.Iterator)
    recs = list(it)
    assert [r.time for r in recs] == [10, 20]
    assert recs[0].process_name == "P1"


def test_iter_record_source_missing_file_is_empty(streaming, tmp_path):
    from seerflow.lanl.parser import parse_auth_line

    assert list(streaming._iter_record_source(tmp_path / "nope.csv", parse_auth_line)) == []


def test_merged_records_global_time_order(streaming):
    from seerflow.lanl.parser import AuthRecord, FlowRecord, ProcRecord

    auth = [
        AuthRecord(1, "U1@D", "U1@D", "C1", "C2", "Negotiate", "Network", "LogOn", False),
        AuthRecord(5, "U1@D", "U1@D", "C1", "C2", "Negotiate", "Network", "LogOn", True),
    ]
    proc = [ProcRecord(2, "U2@D", "C3", "P1", "Start"), ProcRecord(6, "U2@D", "C3", "P1", "End")]
    flow = [FlowRecord(3, 1, "C9", 1, "C8", 443, 6, 5, 4096)]
    merged = list(streaming._merged_records([iter(auth), iter(proc), iter(flow)]))
    assert [r.time for r in merged] == [1, 2, 3, 5, 6]


def test_message_builders_match_build_raw_events(streaming):
    """AC2 parity: streaming messages are byte-identical to validator._build_raw_events."""
    from seerflow.lanl import validator
    from seerflow.lanl.parser import AuthRecord, FlowRecord, ProcRecord

    auth = AuthRecord(
        100, "U1@DOM1", "U5624@DOM1", "C17693", "C528", "Negotiate", "Network", "LogOn", False
    )
    proc = ProcRecord(110, "U2@DOM1", "C9", "P1", "Start")
    flow = FlowRecord(120, 1, "C9999", 1234, "C8888", 443, 6, 5, 4096)

    expected = validator._build_raw_events([auth], [proc], [flow])
    by_src = {e.source_id: e.data.decode() for e in expected}

    assert streaming._auth_message(auth) == by_src["lanl-auth"]
    assert streaming._proc_message(proc) == by_src["lanl-proc"]
    assert streaming._flow_message(flow) == by_src["lanl-flow"]


def test_message_builders_success_auth_branch(streaming):
    """The success branch of _auth_message also matches _build_raw_events."""
    from seerflow.lanl import validator
    from seerflow.lanl.parser import AuthRecord

    auth = AuthRecord(
        100, "U1@DOM1", "U5624@DOM1", "C17693", "C528", "Negotiate", "Network", "LogOn", True
    )
    expected = validator._build_raw_events([auth], [], [])
    assert streaming._auth_message(auth) == expected[0].data.decode()


def test_proc_message_end_action(streaming):
    """_proc_message renders the 'end' action for non-Start records."""
    from seerflow.lanl import validator
    from seerflow.lanl.parser import ProcRecord

    proc = ProcRecord(110, "U2@DOM1", "C9", "P1", "End")
    expected = validator._build_raw_events([], [proc], [])
    assert streaming._proc_message(proc) == expected[0].data.decode()


def test_record_to_raw_applies_offset_and_metadata(streaming):
    from seerflow.lanl.parser import ProcRecord
    from seerflow.receivers.base import RawEvent

    rec = ProcRecord(7, "U2@DOM1", "C9", "P1", "Start")
    raw = streaming._record_to_raw(rec, offset_ns=1_000)
    assert isinstance(raw, RawEvent)
    assert raw.received_ns == 7 * 1_000_000_000 + 1_000
    assert raw.source_type == "syslog"
    assert raw.source_id == "lanl-proc"
    assert raw.metadata == {}


def test_cursor_round_trip(streaming):
    cur = streaming.StreamCursor(
        events_processed=42,
        offset_ns=-123_456,
        positions={"auth": 10, "proc": 5, "flows": 7, "dns": 0},
    )
    blob = streaming._encode_cursor(cur)
    assert isinstance(blob, bytes)
    back = streaming._decode_cursor(blob)
    assert back == cur


def test_decode_cursor_corrupt_returns_none(streaming):
    assert streaming._decode_cursor(b"not json at all") is None
    assert streaming._decode_cursor(b'{"events_processed": "bad"}') is None


async def test_stream_raw_events_rebases_from_first_record(streaming, tmp_path):
    from seerflow.lanl import validator
    from seerflow.receivers.base import RawEvent

    (tmp_path / "proc.csv").write_text(
        "100,U1@DOM1,C1,P1,Start\n300,U2@DOM1,C2,P2,End\n", encoding="utf-8"
    )
    out = [r async for r in streaming.stream_raw_events(tmp_path)]
    assert all(isinstance(r, RawEvent) for r in out)
    assert len(out) == 2
    # first record (min_ts=100s) lands exactly at REPLAY_EPOCH_NS
    assert out[0].received_ns == validator.REPLAY_EPOCH_NS
    # spacing preserved (300-100 = 200 s)
    assert out[1].received_ns - out[0].received_ns == 200 * 1_000_000_000


async def test_stream_raw_events_empty_dir_yields_nothing(streaming, tmp_path):
    out = [r async for r in streaming.stream_raw_events(tmp_path)]
    assert out == []


async def test_stream_rebase_is_additive_constant_vs_s305(streaming, tmp_path):
    """AC3 property: streaming timestamps differ from S-305's shift-all
    rebase only by a single global constant (both are pure additive)."""
    from seerflow.lanl import validator
    from seerflow.lanl.parser import parse_proc_line

    (tmp_path / "proc.csv").write_text(
        "100,U1@DOM1,C1,P1,Start\n250,U2@DOM1,C2,P2,End\n900,U3@DOM1,C3,P3,Start\n",
        encoding="utf-8",
    )
    recs = [
        parse_proc_line(ln)
        for ln in (tmp_path / "proc.csv").read_text(encoding="utf-8").splitlines()
    ]
    s305_raw = validator._build_raw_events([], recs, [])
    max_ts = max(r.received_ns for r in s305_raw)
    s305_off = validator.REPLAY_EPOCH_NS - max_ts - validator.REPLAY_HEADROOM_NS
    s305_ts = sorted(r.received_ns + s305_off for r in s305_raw)

    stream_ts = [r.received_ns async for r in streaming.stream_raw_events(tmp_path)]

    deltas = {s - a for s, a in zip(s305_ts, stream_ts, strict=True)}
    assert len(deltas) == 1  # a single global constant offset


async def test_stream_resume_skips_prefix(streaming, tmp_path):
    from seerflow.lanl import validator

    (tmp_path / "proc.csv").write_text(
        "10,U1@D,C1,P1,Start\n20,U2@D,C2,P2,End\n30,U3@D,C3,P3,Start\n",
        encoding="utf-8",
    )
    full = [r async for r in streaming.stream_raw_events(tmp_path)]
    # The fresh-run offset is the same constant the cursor must restore.
    offset_ns = validator.REPLAY_EPOCH_NS - 10 * 1_000_000_000
    cursor = streaming.StreamCursor(
        events_processed=1,
        offset_ns=offset_ns,
        positions={"auth": 0, "proc": 1, "flows": 0, "dns": 0},
    )
    resumed = [r async for r in streaming.stream_raw_events(tmp_path, resume_cursor=cursor)]
    # one proc line skipped → 2 events, timestamps identical to the full run tail
    assert [r.received_ns for r in resumed] == [r.received_ns for r in full[1:]]
