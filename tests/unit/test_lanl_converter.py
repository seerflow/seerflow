"""Unit tests for the LANL event converter.

Tests follow TDD: written before the implementation exists.
Each test is focused on a single concern.
"""

from __future__ import annotations

import re

import pytest

from seerflow.lanl.parser import AuthRecord, DnsRecord, FlowRecord, ProcRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BRUTE_FORCE_RE = re.compile(
    r"(?i)(authentication fail|login fail|invalid password|failed password|access denied)"
)
ACCEPTED_RE = re.compile(r"(?i)(accepted.*password|session opened|login.*success|authenticated)")
C2_BEACON_RE = re.compile(r"(?i)established.*\d+\.\d+\.\d+\.\d+")

# Minimal fixtures --------------------------------------------------------


def _auth_failure() -> AuthRecord:
    return AuthRecord(
        time=100,
        src_user="U100@DOM1",
        dst_user="U200@DOM2",
        src_computer="C1",
        dst_computer="C2",
        auth_type="NTLM",
        logon_type="Network",
        auth_orientation="LogOn",
        success=False,
    )


def _auth_success() -> AuthRecord:
    return AuthRecord(
        time=200,
        src_user="U300@DOM1",
        dst_user="U400@DOM2",
        src_computer="C3",
        dst_computer="C4",
        auth_type="Kerberos",
        logon_type="Interactive",
        auth_orientation="LogOn",
        success=True,
    )


def _proc_start() -> ProcRecord:
    return ProcRecord(
        time=300,
        user="U500@DOM1",
        computer="C5",
        process_name="cmd.exe",
        start_end="Start",
    )


def _proc_end() -> ProcRecord:
    return ProcRecord(
        time=400,
        user="U600@DOM1",
        computer="C6",
        process_name="powershell.exe",
        start_end="End",
    )


def _flow_record() -> FlowRecord:
    return FlowRecord(
        time=500,
        duration=10,
        src_computer="C7",
        src_port=12345,
        dst_computer="C8",
        dst_port=443,
        protocol=6,
        packet_count=20,
        byte_count=1024,
    )


# ---------------------------------------------------------------------------
# Import target under test (deferred so RED phase still shows import error)
# ---------------------------------------------------------------------------


@pytest.fixture
def converter():
    from seerflow.lanl import converter

    return converter


# ---------------------------------------------------------------------------
# Auth failure tests
# ---------------------------------------------------------------------------


def test_auth_failure_produces_two_events(converter):
    events = converter.convert_auth_record(_auth_failure())
    assert len(events) == 2


def test_auth_failure_user_view_has_users_no_ips(converter):
    events = converter.convert_auth_record(_auth_failure())
    user_view = next(e for e in events if e.related_users)
    assert len(user_view.related_users) > 0
    assert user_view.related_ips == ()


def test_auth_failure_ip_view_has_ips_no_users(converter):
    events = converter.convert_auth_record(_auth_failure())
    ip_view = next(e for e in events if e.related_ips)
    assert len(ip_view.related_ips) > 0
    assert ip_view.related_users == ()


def test_auth_failure_message_matches_brute_force_regex(converter):
    events = converter.convert_auth_record(_auth_failure())
    for ev in events:
        assert BRUTE_FORCE_RE.search(ev.message), (
            f"Message {ev.message!r} does not match brute-force regex"
        )


def test_auth_failure_severity_is_warning(converter):
    from seerflow.models.event import SeverityLevel

    events = converter.convert_auth_record(_auth_failure())
    for ev in events:
        assert ev.severity_id == SeverityLevel.WARNING


def test_auth_failure_source_type_is_syslog(converter):
    events = converter.convert_auth_record(_auth_failure())
    for ev in events:
        assert ev.source_type == "syslog"


def test_auth_failure_user_view_contains_dst_user(converter):
    rec = _auth_failure()
    events = converter.convert_auth_record(rec)
    user_view = next(e for e in events if e.related_users)
    assert "u200" in user_view.related_users


def test_auth_failure_ip_view_contains_src_host_ip(converter):
    from seerflow.lanl.hostmap import host_to_ip

    rec = _auth_failure()
    events = converter.convert_auth_record(rec)
    ip_view = next(e for e in events if e.related_ips)
    expected_ip = host_to_ip(rec.src_computer)
    assert expected_ip in ip_view.related_ips


def test_auth_failure_user_view_has_no_hosts(converter):
    """User-view: no related_hosts to prevent cross-entity contamination."""
    rec = _auth_failure()
    events = converter.convert_auth_record(rec)
    user_view = next(e for e in events if e.related_users)
    assert user_view.related_hosts == ()


def test_auth_failure_ip_view_has_no_hosts(converter):
    """IP-view: no related_hosts to prevent cross-entity contamination."""
    rec = _auth_failure()
    events = converter.convert_auth_record(rec)
    ip_view = next(e for e in events if e.related_ips)
    assert ip_view.related_hosts == ()


# ---------------------------------------------------------------------------
# Auth success tests
# ---------------------------------------------------------------------------


def test_auth_success_produces_two_events(converter):
    events = converter.convert_auth_record(_auth_success())
    assert len(events) == 2


def test_auth_success_message_matches_accepted_regex(converter):
    events = converter.convert_auth_record(_auth_success())
    for ev in events:
        assert ACCEPTED_RE.search(ev.message), (
            f"Message {ev.message!r} does not match accepted regex"
        )


def test_auth_success_severity_is_informational(converter):
    from seerflow.models.event import SeverityLevel

    events = converter.convert_auth_record(_auth_success())
    for ev in events:
        assert ev.severity_id == SeverityLevel.INFORMATIONAL


# ---------------------------------------------------------------------------
# Timestamp tests
# ---------------------------------------------------------------------------


def test_auth_timestamp_in_nanoseconds(converter):
    rec = _auth_failure()
    events = converter.convert_auth_record(rec)
    for ev in events:
        assert ev.timestamp_ns == rec.time * 1_000_000_000


def test_auth_observed_ns_slightly_after_timestamp(converter):
    rec = _auth_failure()
    events = converter.convert_auth_record(rec)
    for ev in events:
        assert ev.observed_ns == rec.time * 1_000_000_000 + 1_000_000


# ---------------------------------------------------------------------------
# Source type
# ---------------------------------------------------------------------------


def test_auth_source_type_is_syslog(converter):
    events = converter.convert_auth_record(_auth_failure())
    for ev in events:
        assert ev.source_type == "syslog"


# ---------------------------------------------------------------------------
# Flow record tests
# ---------------------------------------------------------------------------


def test_flow_produces_one_event(converter):
    events = converter.convert_flow_record(_flow_record())
    assert len(events) == 1


def test_flow_produces_ip_view(converter):
    events = converter.convert_flow_record(_flow_record())
    ev = events[0]
    assert len(ev.related_ips) > 0
    assert ev.related_users == ()


def test_flow_message_matches_c2_beacon_regex(converter):
    events = converter.convert_flow_record(_flow_record())
    ev = events[0]
    assert C2_BEACON_RE.search(ev.message), (
        f"Message {ev.message!r} does not match C2 beacon regex"
    )


def test_flow_source_type_is_syslog(converter):
    events = converter.convert_flow_record(_flow_record())
    assert events[0].source_type == "syslog"


def test_flow_timestamp_in_nanoseconds(converter):
    rec = _flow_record()
    events = converter.convert_flow_record(rec)
    assert events[0].timestamp_ns == rec.time * 1_000_000_000


def test_flow_has_no_hosts(converter):
    """Flow ip-view events must NOT include related_hosts."""
    rec = _flow_record()
    events = converter.convert_flow_record(rec)
    ev = events[0]
    assert ev.related_hosts == ()


def test_flow_related_ips_contains_src_ip(converter):
    from seerflow.lanl.hostmap import host_to_ip

    rec = _flow_record()
    events = converter.convert_flow_record(rec)
    ev = events[0]
    expected_ip = host_to_ip(rec.src_computer)
    assert expected_ip in ev.related_ips


# ---------------------------------------------------------------------------
# DNS record tests (S-315 / FR-081)
# ---------------------------------------------------------------------------


def _dns_record() -> DnsRecord:
    return DnsRecord(time=110, src_computer="C17693", resolved_computer="C5030")


def test_dns_produces_one_event(converter):
    assert len(converter.convert_dns_record(_dns_record())) == 1


def test_dns_produces_ip_view(converter):
    ev = converter.convert_dns_record(_dns_record())[0]
    assert len(ev.related_ips) > 0
    assert ev.related_users == ()
    assert ev.related_hosts == ()


def test_dns_related_ips_contains_resolver_ip(converter):
    from seerflow.lanl.hostmap import host_to_ip

    rec = _dns_record()
    ev = converter.convert_dns_record(rec)[0]
    assert host_to_ip(rec.src_computer) in ev.related_ips


def test_dns_message_matches_c2_beacon_regex(converter):
    ev = converter.convert_dns_record(_dns_record())[0]
    assert C2_BEACON_RE.search(ev.message), (
        f"Message {ev.message!r} does not match C2 beacon regex"
    )


def test_dns_source_type_is_syslog(converter):
    assert converter.convert_dns_record(_dns_record())[0].source_type == "syslog"


def test_dns_timestamp_in_nanoseconds(converter):
    rec = _dns_record()
    assert converter.convert_dns_record(rec)[0].timestamp_ns == rec.time * 1_000_000_000


def test_dns_missing_resolved_marker_kept_verbatim(converter):
    rec = DnsRecord(time=9, src_computer="C17693", resolved_computer="?")
    assert "?" in converter.convert_dns_record(rec)[0].message


def test_dns_message_parity_with_streaming(converter):
    """S-315 AC4: converter message byte-identical to streaming._dns_message."""
    from seerflow.lanl import streaming

    for rec in (
        DnsRecord(110, "C17693", "C5030"),
        DnsRecord(2, "C1", "?"),
        DnsRecord(999999, "C16777215", "C42"),
    ):
        assert converter.convert_dns_record(rec)[0].message == streaming._dns_message(rec)


# ---------------------------------------------------------------------------
# Process record tests
# ---------------------------------------------------------------------------


def test_proc_produces_one_event(converter):
    events = converter.convert_proc_record(_proc_start())
    assert len(events) == 1


def test_proc_produces_user_view(converter):
    events = converter.convert_proc_record(_proc_start())
    ev = events[0]
    assert len(ev.related_users) > 0
    assert ev.related_ips == ()


def test_proc_source_type_is_syslog(converter):
    events = converter.convert_proc_record(_proc_start())
    assert events[0].source_type == "syslog"


def test_proc_timestamp_in_nanoseconds(converter):
    rec = _proc_start()
    events = converter.convert_proc_record(rec)
    assert events[0].timestamp_ns == rec.time * 1_000_000_000


def test_proc_related_users_contains_normalized_user(converter):
    rec = _proc_start()
    events = converter.convert_proc_record(rec)
    ev = events[0]
    assert "u500" in ev.related_users


def test_proc_has_no_hosts(converter):
    """Process user-view events must NOT include related_hosts."""
    rec = _proc_start()
    events = converter.convert_proc_record(rec)
    ev = events[0]
    assert ev.related_hosts == ()


def test_proc_start_message_format(converter):
    rec = _proc_start()
    events = converter.convert_proc_record(rec)
    ev = events[0]
    assert "process start" in ev.message.lower()
    assert rec.process_name in ev.message


def test_proc_end_message_format(converter):
    rec = _proc_end()
    events = converter.convert_proc_record(rec)
    ev = events[0]
    assert "process end" in ev.message.lower()
    assert rec.process_name in ev.message


def test_proc_severity_is_informational(converter):
    from seerflow.models.event import SeverityLevel

    events = converter.convert_proc_record(_proc_start())
    assert events[0].severity_id == SeverityLevel.INFORMATIONAL


def test_each_event_has_unique_event_id(converter):
    events = converter.convert_auth_record(_auth_failure())
    ids = [ev.event_id for ev in events]
    assert len(ids) == len(set(ids)), "Duplicate event_ids found"
