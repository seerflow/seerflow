"""Drain3 parser wrapper — streaming log template extraction."""
from __future__ import annotations

import re

_IP_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _mask_tokens(message: str) -> str:
    """Pre-process message by masking IPs and UUIDs for better template stability."""
    message = _IP_RE.sub("<IP>", message)
    return _UUID_RE.sub("<UUID>", message)
