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

import logging
from collections.abc import Sequence
from typing import Any, Final

from seerflow.models.event import SeerflowEvent
from seerflow.models.ioc_match import IoCMatch

_log = logging.getLogger("seerflow")

IOC_MATCHES_MAX_ENTRIES: Final[int] = 32

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


def _clamp_confidence(raw: int) -> int:
    """Clamp STIX 2.1 confidence (declared 0–100) into the documented range.

    Feed implementations occasionally emit negative or > 100 values; the
    matcher does not pre-validate this, so we clamp at the boundary where
    we map to severity/risk.
    """
    if raw < 0:
        return 0
    if raw > 100:
        return 100
    return raw


def _severity_for_confidence(confidence: int) -> int:
    """Map STIX confidence (0–100) to Seerflow ``SeverityLevel`` integer.

    Bands are intentionally conservative — see story S-069 brainstorm
    notes for the SOC-noise rationale (STIX's High band starting at 50
    pages on coin-flip indicators; we require ≥ 67 to mark "high").

    Returns one of ``2`` (low informational), ``3`` (medium), ``4`` (high),
    ``5`` (critical).
    """
    c = _clamp_confidence(confidence)
    if c < 33:
        return 2
    if c < 67:
        return 3
    if c < 85:
        return 4
    return 5


def _ioc_match_payload(match: IoCMatch) -> dict[str, Any]:
    ind = match.indicator
    return {
        "value": match.value,
        "type": match.type,
        "source_feed": ind.source_feed,
        "confidence": _clamp_confidence(ind.confidence),
        "kill_chain_phases": list(ind.kill_chain_phases),
        "entity_kind": match.entity_kind,
    }


class IoCAlertBuilder:
    """Stateless builder for IoC alerts + enriched event attributes.

    Pure-function methods only — no I/O, no shared state. Threading-safe
    by construction.
    """

    def enriched_attributes(
        self,
        event: SeerflowEvent,
        matches: Sequence[IoCMatch],
    ) -> dict[str, Any]:
        new_attrs: dict[str, Any] = dict(event.attributes)
        if not matches:
            return new_attrs
        if len(matches) > IOC_MATCHES_MAX_ENTRIES:
            _log.warning(
                "ioc_matches truncated: event=%s matches=%d cap=%d",
                event.event_id,
                len(matches),
                IOC_MATCHES_MAX_ENTRIES,
            )
            kept = list(matches)[:IOC_MATCHES_MAX_ENTRIES]
        else:
            kept = list(matches)
        new_attrs["ioc_matches"] = [_ioc_match_payload(m) for m in kept]
        return new_attrs
