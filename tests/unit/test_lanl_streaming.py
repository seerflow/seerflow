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
