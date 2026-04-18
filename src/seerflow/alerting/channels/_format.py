"""Shared formatting helpers for S-163 channel targets."""

from __future__ import annotations

# Canonical 0-6 severity labels, aligned with ``SeverityLevel`` enum names in
# ``seerflow.models.event``. Centralised so every channel renders the same
# human-readable label for the same severity_id.
_SEVERITY_NAME: dict[int, str] = {
    0: "TRACE",
    1: "INFORMATIONAL",
    2: "NOTICE",
    3: "WARNING",
    4: "ERROR",
    5: "CRITICAL",
    6: "FATAL",
}


def severity_name(sev: int) -> str:
    """Return the canonical severity label for ``sev``, or ``str(sev)``."""
    return _SEVERITY_NAME.get(sev, str(sev))
