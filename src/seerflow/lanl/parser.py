"""LANL Unified Host and Network Dataset CSV parser.

Parses the four CSV file types from the LANL dataset:
  - Authentication events (auth.txt / redauth.txt)
  - Process events (proc.txt / redproc.txt)
  - Network flow events (flows.txt / redflows.txt)
  - Red-team compromise labels (redteam.txt)

All records are frozen dataclasses (immutable, slotted) so they are safe to
share across threads and can be used as dict/set keys.

References:
  Turcotte et al., "Unified Host and Network Data Set", 2017.
  https://csr.lanl.gov/data/2017.html
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthRecord:
    """Single row from the LANL authentication log.

    Fields follow the published CSV column order::

        time, src_user, dst_user, src_computer, dst_computer,
        auth_type, logon_type, auth_orientation, success
    """

    time: int
    src_user: str
    dst_user: str
    src_computer: str
    dst_computer: str
    auth_type: str
    logon_type: str
    auth_orientation: str
    success: bool


@dataclass(frozen=True, slots=True)
class ProcRecord:
    """Single row from the LANL process log.

    Fields::

        time, user, computer, process_name, start_end
    """

    time: int
    user: str
    computer: str
    process_name: str
    start_end: str


@dataclass(frozen=True, slots=True)
class FlowRecord:
    """Single row from the LANL network flow log.

    Fields::

        time, duration, src_computer, src_port,
        dst_computer, dst_port, protocol, packet_count, byte_count

    Ports are stored verbatim as strings: LANL anonymizes non-well-known
    ports to a consistent ``N<id>`` token (well-known ports stay numeric),
    and missing values are the marker ``?``. Ports are categorical
    identifiers here — only rendered into the event message, never compared
    numerically — so the raw token is preserved without loss.
    """

    time: int
    duration: int
    src_computer: str
    src_port: str
    dst_computer: str
    dst_port: str
    protocol: int
    packet_count: int
    byte_count: int


@dataclass(frozen=True, slots=True)
class RedTeamRecord:
    """Single row from the LANL red-team label file.

    Fields::

        time, user, src_computer, dst_computer
    """

    time: int
    user: str
    src_computer: str
    dst_computer: str


@dataclass(frozen=True, slots=True)
class DnsRecord:
    """Single row from the LANL DNS log (``dns.txt``).

    Fields follow the published CSV column order::

        time, src_computer, resolved_computer

    ``resolved_computer`` may be the missing marker ``?`` (kept verbatim).
    DNS records carry no user and no own red-team label; they contribute to
    detection via the *resolving* host's entity (S-315 / FR-081).
    """

    time: int
    src_computer: str
    resolved_computer: str


# Public union type for all record variants.
AnyRecord = AuthRecord | ProcRecord | FlowRecord | RedTeamRecord | DnsRecord


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------


def _parse_int(value: str) -> int:
    """Convert a field value to int; raises ValueError on bad input."""
    return int(value)


def _parse_port(value: str) -> str:
    """Return a LANL port field verbatim.

    Ports are categorical, not numeric: well-known ports appear as their
    number (``"389"``), non-well-known ports are anonymized to a consistent
    ``"N<id>"`` token, and missing values are ``"?"``. The raw token is kept
    so the anonymized identity (and the missing marker) survive intact.
    """
    return value


def _parse_success(value: str) -> bool:
    """Convert ``Success``/``Fail`` to bool."""
    return value.strip().lower() == "success"


# ---------------------------------------------------------------------------
# Public parse functions
# ---------------------------------------------------------------------------


def parse_auth_line(line: str) -> AuthRecord:
    """Parse a single authentication log CSV line into an :class:`AuthRecord`.

    Expected column order::

        time, src_user, dst_user, src_computer, dst_computer,
        auth_type, logon_type, auth_orientation, Success|Fail

    Args:
        line: A raw CSV line (no newline required).

    Returns:
        An immutable :class:`AuthRecord`.

    Raises:
        ValueError: If the line does not have exactly 9 fields.
    """
    parts = line.strip().split(",")
    if len(parts) != 9:
        msg = f"auth line must have 9 fields, got {len(parts)}: {line!r}"
        raise ValueError(msg)
    return AuthRecord(
        time=_parse_int(parts[0]),
        src_user=parts[1],
        dst_user=parts[2],
        src_computer=parts[3],
        dst_computer=parts[4],
        auth_type=parts[5],
        logon_type=parts[6],
        auth_orientation=parts[7],
        success=_parse_success(parts[8]),
    )


def parse_proc_line(line: str) -> ProcRecord:
    """Parse a single process log CSV line into a :class:`ProcRecord`.

    Expected column order::

        time, user, computer, process_name, Start|End

    Args:
        line: A raw CSV line.

    Returns:
        An immutable :class:`ProcRecord`.

    Raises:
        ValueError: If the line does not have exactly 5 fields.
    """
    parts = line.strip().split(",")
    if len(parts) != 5:
        msg = f"proc line must have 5 fields, got {len(parts)}: {line!r}"
        raise ValueError(msg)
    return ProcRecord(
        time=_parse_int(parts[0]),
        user=parts[1],
        computer=parts[2],
        process_name=parts[3],
        start_end=parts[4],
    )


def parse_flow_line(line: str) -> FlowRecord:
    """Parse a single network flow CSV line into a :class:`FlowRecord`.

    Expected column order::

        time, duration, src_computer, src_port,
        dst_computer, dst_port, protocol, packet_count, byte_count

    Ports are kept verbatim as strings (numeric, anonymized ``N<id>``, or the
    missing marker ``?``) — see :class:`FlowRecord`.

    Args:
        line: A raw CSV line.

    Returns:
        An immutable :class:`FlowRecord`.

    Raises:
        ValueError: If the line does not have exactly 9 fields.
    """
    parts = line.strip().split(",")
    if len(parts) != 9:
        msg = f"flow line must have 9 fields, got {len(parts)}: {line!r}"
        raise ValueError(msg)
    return FlowRecord(
        time=_parse_int(parts[0]),
        duration=_parse_int(parts[1]),
        src_computer=parts[2],
        src_port=_parse_port(parts[3]),
        dst_computer=parts[4],
        dst_port=_parse_port(parts[5]),
        protocol=_parse_int(parts[6]),
        packet_count=_parse_int(parts[7]),
        byte_count=_parse_int(parts[8]),
    )


def parse_redteam_line(line: str) -> RedTeamRecord:
    """Parse a single red-team label CSV line into a :class:`RedTeamRecord`.

    Expected column order::

        time, user, src_computer, dst_computer

    Args:
        line: A raw CSV line.

    Returns:
        An immutable :class:`RedTeamRecord`.

    Raises:
        ValueError: If the line does not have exactly 4 fields.
    """
    parts = line.strip().split(",")
    if len(parts) != 4:
        msg = f"redteam line must have 4 fields, got {len(parts)}: {line!r}"
        raise ValueError(msg)
    return RedTeamRecord(
        time=_parse_int(parts[0]),
        user=parts[1],
        src_computer=parts[2],
        dst_computer=parts[3],
    )


def parse_dns_line(line: str) -> DnsRecord:
    """Parse a single DNS log CSV line into a :class:`DnsRecord`.

    Expected column order::

        time, src_computer, resolved_computer

    ``resolved_computer`` may be the LANL missing marker ``?`` — it is kept
    verbatim (no host-to-IP derivation; only the *resolving* host drives the
    entity/match path).

    Args:
        line: A raw CSV line.

    Returns:
        An immutable :class:`DnsRecord`.

    Raises:
        ValueError: If the line does not have exactly 3 fields.
    """
    parts = line.strip().split(",")
    if len(parts) != 3:
        msg = f"dns line must have 3 fields, got {len(parts)}: {line!r}"
        raise ValueError(msg)
    return DnsRecord(
        time=_parse_int(parts[0]),
        src_computer=parts[1],
        resolved_computer=parts[2],
    )


# ---------------------------------------------------------------------------
# Streaming iterator
# ---------------------------------------------------------------------------

_PARSERS: dict[str, Callable[[str], AnyRecord]] = {
    "auth": parse_auth_line,
    "proc": parse_proc_line,
    "flow": parse_flow_line,
    "redteam": parse_redteam_line,
    "dns": parse_dns_line,
}


def iter_records(
    path: Path,
    record_type: str,
) -> Iterator[AnyRecord]:
    """Stream records from a LANL CSV file (plain or gzip-compressed).

    The file is read line by line so that arbitrarily large files can be
    processed without loading them entirely into memory.

    Args:
        path: Path to the CSV file.  Files ending in ``.gz`` are
              decompressed transparently.
        record_type: One of ``"auth"``, ``"proc"``, ``"flow"``,
                     or ``"redteam"``.

    Yields:
        Parsed record objects of the appropriate type.

    Raises:
        ValueError: If *record_type* is not recognised.
    """
    if record_type not in _PARSERS:
        valid = ", ".join(sorted(_PARSERS))
        msg = f"Unknown record_type {record_type!r}. Valid options: {valid}"
        raise ValueError(msg)

    parse_fn = _PARSERS[record_type]
    suffix = path.suffix.lower()

    if suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for raw in fh:
                stripped = raw.strip()
                if stripped:
                    yield parse_fn(stripped)
    else:
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                stripped = raw.strip()
                if stripped:
                    yield parse_fn(stripped)
