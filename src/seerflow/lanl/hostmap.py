"""Deterministic host-to-IP mapper for LANL anonymized computer names.

LANL anonymizes computers as ``C{N}`` where N is a positive integer
(e.g. C1, C528, C17693).  This module maps each name to a synthetic
private IP address in the ``10.0.0.0/8`` range using the formula::

    10.{(N >> 16) & 0xFF}.{(N >> 8) & 0xFF}.{N & 0xFF}

The mapping is deterministic and collision-free for all valid N values
(1 - 16,777,215 = 0xFFFFFF).
"""

from __future__ import annotations

import re

_PATTERN: re.Pattern[str] = re.compile(r"^C(\d+)$")
_MAX_N: int = 0xFFFFFF  # 16,777,215 — largest value that fits in 3 octets


def host_to_ip(hostname: str) -> str:
    """Map a LANL anonymized hostname to a deterministic private IP.

    Parameters
    ----------
    hostname:
        A LANL computer name in the form ``C{N}`` where N is a positive
        integer (e.g. ``C1``, ``C528``, ``C17693``).

    Returns
    -------
    str
        A dotted-decimal IPv4 address in the ``10.0.0.0/8`` range.

    Raises
    ------
    ValueError
        If *hostname* is empty, does not match the ``C{digits}`` pattern,
        N equals zero, or N exceeds 16,777,215.
    """
    if not hostname:
        raise ValueError("hostname must not be empty")

    match = _PATTERN.match(hostname)
    if match is None:
        raise ValueError(f"hostname {hostname!r} does not match the expected C{{N}} pattern")

    n = int(match.group(1))

    if n == 0:
        raise ValueError("hostname C0 is invalid: N must be a positive integer")

    if n > _MAX_N:
        raise ValueError(
            f"hostname {hostname!r} maps to N={n} which exceeds the 3-byte maximum of {_MAX_N}"
        )

    octet1 = (n >> 16) & 0xFF
    octet2 = (n >> 8) & 0xFF
    octet3 = n & 0xFF
    return f"10.{octet1}.{octet2}.{octet3}"
