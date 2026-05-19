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
