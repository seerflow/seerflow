"""S-069: IoC alert builder + enriched-attributes helpers.

Pure-function-style helpers consumed by the pipeline handler to turn an
``IoCMatch`` into an ``Alert(alert_type="ioc", ...)`` and to enrich the
matching ``SeerflowEvent.attributes`` with TI context.

The MITRE tactic mapping is a static table; phases not in the table
contribute no tactics (we never fabricate). Severity bands intentionally
skew conservative — see the module docstring on ``_severity_for_confidence``
for the rationale.
"""

from __future__ import annotations

from typing import Final

_STIX_PHASE_TO_ATTACK_TACTIC: Final[dict[str, str]] = {
    "reconnaissance": "TA0043",
    "resource-development": "TA0042",
    "initial-access": "TA0001",
    "execution": "TA0002",
    "persistence": "TA0003",
    "privilege-escalation": "TA0004",
    "defense-evasion": "TA0005",
    "credential-access": "TA0006",
    "discovery": "TA0007",
    "lateral-movement": "TA0008",
    "collection": "TA0009",
    "command-and-control": "TA0011",
    "exfiltration": "TA0010",
    "impact": "TA0040",
}


def _normalise_phase(raw: str) -> str:
    return raw.strip().lower().replace("_", "-")


def _stix_phases_to_tactics(phases: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in phases:
        tactic = _STIX_PHASE_TO_ATTACK_TACTIC.get(_normalise_phase(raw))
        if tactic is None or tactic in seen:
            continue
        seen.add(tactic)
        out.append(tactic)
    return tuple(out)
