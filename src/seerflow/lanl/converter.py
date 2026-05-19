"""LANL record to SeerflowEvent converter.

Transforms parsed LANL records (AuthRecord, ProcRecord, FlowRecord) into
SeerflowEvent instances suitable for the Seerflow correlation engine.

Design: Entity-type split
--------------------------
The built-in correlation rules key on ``entity_type``, which
``infer_entity_type()`` resolves via priority: ip > user > host.

Auth events produce TWO SeerflowEvents:
  1. user-view  — related_users populated, related_ips empty → entity_type="user"
  2. ip-view    — related_ips populated, related_users empty → entity_type="ip"

Process events produce ONE SeerflowEvent (user-view).
Flow events produce ONE SeerflowEvent (ip-view).

Message formats
---------------
Messages are crafted to match the regex patterns in the built-in
correlation/Sigma rules so that brute-force, credential-stuffing, and
C2-beaconing rules fire correctly during validation.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from seerflow.lanl.hostmap import host_to_ip
from seerflow.models.entity import normalize_username
from seerflow.models.event import SeerflowEvent, SeverityLevel

if TYPE_CHECKING:
    from seerflow.lanl.parser import AuthRecord, DnsRecord, FlowRecord, ProcRecord

# ---------------------------------------------------------------------------
# Auth record converter
# ---------------------------------------------------------------------------


def convert_auth_record(rec: AuthRecord) -> list[SeerflowEvent]:
    """Convert one LANL auth record to user-view + ip-view SeerflowEvents.

    Auth failure messages match the brute-force rule regex::
        (?i)(authentication fail|login fail|invalid password|failed password|access denied)

    Auth success messages match the credential-stuffing / accepted regex::
        (?i)(accepted.*password|session opened|login.*success|authenticated)

    Returns a list of exactly two SeerflowEvents.
    """
    timestamp_ns = rec.time * 1_000_000_000
    observed_ns = timestamp_ns + 1_000_000

    dst_user, _domain = normalize_username(rec.dst_user)
    src_ip = host_to_ip(rec.src_computer)

    if rec.success:
        message = f"Accepted password for {dst_user} session opened from {rec.src_computer}"
        severity = SeverityLevel.INFORMATIONAL
    else:
        message = (
            f"authentication failure for {dst_user} from {rec.src_computer} via {rec.auth_type}"
        )
        severity = SeverityLevel.WARNING

    # User-view: ONLY related_users (no related_hosts/ips) to avoid
    # cross-entity contamination in the window buffer. Host windows
    # would otherwise accumulate events from multiple users, causing
    # user-typed rules to fire spuriously.
    user_view = SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=timestamp_ns,
        observed_ns=observed_ns,
        severity_id=severity,
        message=message,
        source_type="syslog",
        related_users=(dst_user,),
        related_ips=(),
        related_hosts=(),
    )

    # IP-view: ONLY related_ips for the same reason.
    ip_view = SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=timestamp_ns,
        observed_ns=observed_ns,
        severity_id=severity,
        message=message,
        source_type="syslog",
        related_ips=(src_ip,),
        related_users=(),
        related_hosts=(),
    )

    return [user_view, ip_view]


# ---------------------------------------------------------------------------
# Process record converter
# ---------------------------------------------------------------------------


def convert_proc_record(rec: ProcRecord) -> list[SeerflowEvent]:
    """Convert one LANL process record to a single SeerflowEvent (user-view).

    Returns a single-element list for API consistency.
    """
    timestamp_ns = rec.time * 1_000_000_000
    observed_ns = timestamp_ns + 1_000_000

    username, _domain = normalize_username(rec.user)

    action = "start" if rec.start_end.lower() == "start" else "end"
    message = f"process {action}: {rec.process_name} by {username} on {rec.computer}"

    event = SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=timestamp_ns,
        observed_ns=observed_ns,
        severity_id=SeverityLevel.INFORMATIONAL,
        message=message,
        source_type="syslog",
        related_users=(username,),
        related_ips=(),
        related_hosts=(),
    )

    return [event]


# ---------------------------------------------------------------------------
# Flow record converter
# ---------------------------------------------------------------------------


def convert_flow_record(rec: FlowRecord) -> list[SeerflowEvent]:
    """Convert one LANL flow record to a single SeerflowEvent (ip-view).

    The message matches the C2-beaconing rule regex::
        (?i)established.*\\d+\\.\\d+\\.\\d+\\.\\d+

    Returns a single-element list for API consistency.
    """
    timestamp_ns = rec.time * 1_000_000_000
    observed_ns = timestamp_ns + 1_000_000

    src_ip = host_to_ip(rec.src_computer)
    dst_ip = host_to_ip(rec.dst_computer)

    message = (
        f"flow established {dst_ip}:{rec.dst_port} from {src_ip}:{rec.src_port} {rec.byte_count}B"
    )

    event = SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=timestamp_ns,
        observed_ns=observed_ns,
        severity_id=SeverityLevel.INFORMATIONAL,
        message=message,
        source_type="syslog",
        related_ips=(src_ip,),
        related_users=(),
        related_hosts=(),
    )

    return [event]


# ---------------------------------------------------------------------------
# DNS record converter (S-315 / FR-081)
# ---------------------------------------------------------------------------


def convert_dns_record(rec: DnsRecord) -> list[SeerflowEvent]:
    """Convert one LANL DNS record to a single SeerflowEvent (ip-view).

    The DNS lookup is attributed to the *resolving* host's deterministic IP
    so the event keys on an ``ip`` entity that the built-in C2-beaconing
    rule (and red-team ground-truth matching) already use. The message is
    produced by :func:`seerflow.lanl.streaming._dns_message` so the
    streaming and in-memory ingest paths are byte-identical by construction
    (S-315 AC4). Returns a single-element list for API consistency.
    """
    from seerflow.lanl.streaming import _dns_message

    timestamp_ns = rec.time * 1_000_000_000
    observed_ns = timestamp_ns + 1_000_000

    src_ip = host_to_ip(rec.src_computer)

    event = SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=timestamp_ns,
        observed_ns=observed_ns,
        severity_id=SeverityLevel.INFORMATIONAL,
        message=_dns_message(rec),
        source_type="syslog",
        related_ips=(src_ip,),
        related_users=(),
        related_hosts=(),
    )

    return [event]
