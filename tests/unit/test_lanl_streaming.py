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


def test_dns_message_is_detection_attributable(streaming):
    """S-315 AC2/AC4: DNS message carries the resolver IP + beacon tokens."""
    from seerflow.lanl.hostmap import host_to_ip
    from seerflow.lanl.parser import DnsRecord

    rec = DnsRecord(2, "C17693", "C5030")
    msg = streaming._dns_message(rec)
    assert "beacon" in msg
    assert "established" in msg
    assert host_to_ip("C17693") in msg
    assert "C5030" in msg


def test_dns_message_preserves_missing_resolved_marker(streaming):
    from seerflow.lanl.parser import DnsRecord

    msg = streaming._dns_message(DnsRecord(2, "C17693", "?"))
    assert "?" in msg


def test_dns_message_matches_c2_beaconing_rule(streaming):
    """S-315 AC2: the DNS message must satisfy the built-in c2-beaconing regex."""
    import re
    from pathlib import Path

    import yaml

    from seerflow.lanl.parser import DnsRecord

    rule_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "seerflow"
        / "correlation"
        / "rules"
        / "c2_beaconing.yml"
    )
    rule = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
    pattern = rule["sources"][0]["conditions"]["message"]
    msg = streaming._dns_message(DnsRecord(110, "C17693", "C5030"))
    assert re.search(pattern, msg) is not None


def test_record_to_raw_dns_branch(streaming):
    from seerflow.lanl.parser import DnsRecord
    from seerflow.receivers.base import RawEvent

    rec = DnsRecord(7, "C17693", "C5030")
    raw = streaming._record_to_raw(rec, offset_ns=1_000)
    assert isinstance(raw, RawEvent)
    assert raw.received_ns == 7 * 1_000_000_000 + 1_000
    assert raw.source_type == "syslog"
    assert raw.source_id == "lanl-dns"
    assert raw.metadata == {}


def test_dns_cursor_name_mapping(streaming):
    assert streaming._CURSOR_NAME_BY_SOURCE_ID["lanl-dns"] == "dns"
    assert streaming._SOURCE_BY_TYPE["DnsRecord"] == "lanl-dns"


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


def test_decode_cursor_none_input_returns_none(streaming):
    """Absent cursor (``load_state`` miss → ``None``) → ``None`` (start fresh)."""
    assert streaming._decode_cursor(None) is None


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


def test_validator_exposes_streaming_delegator():
    import inspect

    from seerflow.lanl import validator

    assert hasattr(validator, "run_streaming_validation")
    # Additive only: existing entrypoints untouched, no docstring overclaim.
    src = inspect.getsource(validator)
    assert "def run_validation(" in src  # S-305 entrypoint still present
    assert "def run_validation_async(" in src


def test_lanl_package_reexports_streaming_entrypoint():
    import seerflow.lanl as lanl_pkg

    assert "run_streaming_validation" in lanl_pkg.__all__
    assert hasattr(lanl_pkg, "run_streaming_validation")


def test_read_redteam_missing_file_is_empty(streaming, tmp_path):
    """`_read_redteam` returns [] when redteam.csv is absent (graceful)."""
    assert streaming._read_redteam(tmp_path) == []


def test_validator_delegator_forwards_to_streaming(monkeypatch, tmp_path):
    """`validator.run_streaming_validation` is a thin forwarder into
    `streaming.run_streaming_validation` (covers the additive hook body)."""
    from seerflow.lanl import streaming as streaming_mod
    from seerflow.lanl import validator

    captured: dict[str, object] = {}

    def _fake(dataset_dir, *, checkpoint_interval, max_events):
        captured["args"] = (dataset_dir, checkpoint_interval, max_events)
        return "SENTINEL"

    monkeypatch.setattr(streaming_mod, "run_streaming_validation", _fake)
    out = validator.run_streaming_validation(tmp_path, checkpoint_interval=7, max_events=3)
    assert out == "SENTINEL"
    assert captured["args"] == (tmp_path, 7, 3)


def test_run_streaming_validation_sync_wrapper_empty_dataset(streaming, tmp_path):
    """Sync wrapper over an empty dataset → zero-metric result, no crash
    (covers run_streaming_validation + the no-events scoring path)."""
    result = streaming.run_streaming_validation(tmp_path, checkpoint_interval=5)
    assert result.total_events_processed == 0
    assert result.precision == 0.0
    assert result.throughput_events_per_s == 0.0
    assert result.mean_event_latency_s == 0.0


def test_streaming_iteration_is_bounded_memory(streaming, tmp_path):
    """AC6 (CI-light): iterating a large synthetic stream does not grow RSS
    proportionally to stream length (no list/sort/read_text buffering)."""
    import asyncio
    import resource

    big = tmp_path / "proc.csv"
    with big.open("w", encoding="utf-8") as fh:
        for i in range(50_000):
            fh.write(f"{i},U{i}@DOM1,C{i % 97},P{i % 13},Start\n")

    async def _consume() -> int:
        n = 0
        async for _raw in streaming.stream_raw_events(tmp_path):
            n += 1
        return n

    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    count = asyncio.run(_consume())
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert count == 50_000
    # ru_maxrss is KB on Linux; 50k streamed events must not add >100 MB.
    assert (after - before) < 100 * 1024


def test_streaming_rss_flat_as_stream_scales(streaming, tmp_path):
    """AC6 proxy: peak RSS delta does NOT grow with stream length — the
    10x-longer stream must not cost ~10x the memory (bounded-memory
    behaviour, validated FAST on tiny synthetic streams)."""
    import asyncio
    import resource

    def _write(path, n):
        with path.open("w", encoding="utf-8") as fh:
            for i in range(n):
                fh.write(f"{i},U{i}@D,C{i % 97},P{i % 13},Start\n")

    async def _consume(d) -> int:
        c = 0
        async for _ in streaming.stream_raw_events(d):
            c += 1
        return c

    small_dir = tmp_path / "small"
    big_dir = tmp_path / "big"
    small_dir.mkdir()
    big_dir.mkdir()
    _write(small_dir / "proc.csv", 5_000)
    _write(big_dir / "proc.csv", 50_000)

    b0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert asyncio.run(_consume(small_dir)) == 5_000
    b1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert asyncio.run(_consume(big_dir)) == 50_000
    b2 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    small_delta = max(b1 - b0, 0)
    big_delta = max(b2 - b1, 0)
    # 10x longer stream must not cost ~10x memory; allow generous slack for
    # interpreter noise but reject linear-in-length growth.
    assert big_delta <= small_delta + 20 * 1024  # < +20 MB for 10x length


@pytest.mark.skipif(
    not __import__("os").environ.get("LANL_STREAM_HEAVY"),
    reason="heavy >=10M-event / real-dataset RSS assertion is operator-driven",
)
def test_streaming_heavy_slice_under_rss_envelope(streaming, tmp_path):  # pragma: no cover
    import asyncio
    import resource

    big = tmp_path / "proc.csv"
    with big.open("w", encoding="utf-8") as fh:
        for i in range(10_000_000):
            fh.write(f"{i},U{i}@D,C{i % 997},P{i % 31},Start\n")

    async def _consume() -> int:
        n = 0
        async for _ in streaming.stream_raw_events(tmp_path):
            n += 1
        return n

    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    n = asyncio.run(_consume())
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert n == 10_000_000
    assert (after - before) < 500 * 1024  # <500 MB RSS (NFR-014)
