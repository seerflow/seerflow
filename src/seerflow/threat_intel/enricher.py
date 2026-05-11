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
import uuid as _uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import msgspec

from seerflow.models.alert import Alert
from seerflow.models.entity import infer_entity_type, sanitize_for_log
from seerflow.models.event import SeverityLevel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models._types import EntityType
    from seerflow.models.event import SeerflowEvent
    from seerflow.models.ioc_match import IoCMatch

_log = logging.getLogger("seerflow")

IOC_MATCHES_MAX_ENTRIES: Final[int] = 32

# Cap the indicator value length embedded in `Alert.dedup_key` so a hostile or
# pathologically-long indicator (e.g. a ~4 KB URL) cannot inflate the unique
# `alerts.dedup_key` TEXT index. Mirrors the front-end's 256-char wire cap with
# headroom for the `ioc:{type}:` and `:{entity_uuid}` framing.
_DEDUP_VALUE_MAX_LEN: Final[int] = 512

_KIND_TO_ENTITY_SLOT: Final[dict[str, tuple[str, EntityType]]] = {
    # entity_kind in IoCMatch -> (related_* attribute name, EntityType label)
    "ip": ("related_ips", "ip"),
    "domain": ("related_domains", "domain"),
}

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
    """Lowercase, strip, and kebab-case a STIX kill-chain phase name."""
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
    """Clamp STIX 2.1 confidence (declared 0-100) into the documented range.

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
    """Map STIX confidence (0-100) to Seerflow ``SeverityLevel`` integer.

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


def _alert_uuid5(event: SeerflowEvent, match: IoCMatch, entity_uuid: str) -> str:
    """Derive a deterministic UUID5 alert_id seeded by (type, value, entity, ts, source)."""
    seed = f"ioc:{match.type}:{match.value}:{entity_uuid}:{event.timestamp_ns}:{event.source_type}"
    return str(_uuid.uuid5(_uuid.NAMESPACE_DNS, seed))


def _ioc_match_payload(match: IoCMatch) -> dict[str, Any]:
    """Serialise an ``IoCMatch`` into the JSON-safe shape stored under
    ``SeerflowEvent.attributes['ioc_matches']`` and re-emitted by
    ``EventResponse.ioc_matches``. Only the six documented fields are kept;
    no `entity_uuid` is included by design (a match may have no linkable
    entity — see ``IoCAlertBuilder.select_entity_uuid``)."""
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
        """Return a fresh ``attributes`` dict for *event* with an
        ``ioc_matches`` payload appended. Never mutates the input event.
        Caps the payload to ``IOC_MATCHES_MAX_ENTRIES`` and logs WARNING."""
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
            kept: Sequence[IoCMatch] = matches[:IOC_MATCHES_MAX_ENTRIES]
        else:
            kept = matches
        new_attrs["ioc_matches"] = [_ioc_match_payload(m) for m in kept]
        return new_attrs

    def select_entity_uuid(
        self,
        event: SeerflowEvent,
        match: IoCMatch,
        entity_refs: tuple[str, ...],
        typed_for_edges: Sequence[tuple[str, str]],
    ) -> tuple[str, str, EntityType]:
        """Resolve the entity UUID for *match* using positional alignment.

        Pre-condition: ``typed_for_edges`` is co-indexed with ``entity_refs``
        (both built in the same single-pass loop in ``pipeline.handler``).
        For ``entity_kind ∈ {"ip", "domain"}`` the match's ``value`` is
        looked up in the matching ``event.related_*`` tuple to find its
        index, then the n-th typed entry of the same label is returned.

        Returns ``("", value, label)`` when no positional match is found
        (URL / hash kinds, or value missing from the related-tuple — the
        caller increments ``dropped_entity_uuid_lookups_total``).
        """
        slot = _KIND_TO_ENTITY_SLOT.get(match.entity_kind)
        if slot is None:
            # URL / hash kinds — no slot in related_*; return empty entity_uuid.
            return ("", match.value, infer_entity_type(event))
        attr_name, label = slot
        raw_values = getattr(event, attr_name, ())
        try:
            idx = list(raw_values).index(match.value)
        except ValueError:
            return ("", match.value, label)
        # typed_for_edges is built in the same order as entity_refs; walk the
        # typed list and pick the n-th positional match for our entity label.
        seen = 0
        for type_name, uid in typed_for_edges:
            if type_name == label:
                if seen == idx:
                    return (uid, match.value, label)
                seen += 1
        return ("", match.value, label)

    def build_alert(
        self,
        match: IoCMatch,
        event: SeerflowEvent,
        *,
        entity_uuid: str,
        entity_value: str,
        entity_type: EntityType,
    ) -> Alert:
        if match.event_id != str(event.event_id):
            raise ValueError(
                f"event_id mismatch: match={match.event_id!r} event={event.event_id!r}"
            )
        ind = match.indicator
        clamped = _clamp_confidence(ind.confidence)
        tactics = _stix_phases_to_tactics(ind.kill_chain_phases)
        risk = clamped / 100.0
        severity = _severity_for_confidence(clamped)
        # Sanitize feed-controlled strings before they reach the alert
        # description: indicator values flow into log lines and downstream
        # sink payloads (PagerDuty / OTLP / WS), and a hostile feed could
        # otherwise embed CR / LF / ANSI sequences that corrupt log
        # aggregators or terminal output. Same defence already applied to
        # related-entity logging in ``pipeline/handler.py``.
        safe_value = sanitize_for_log(match.value)
        safe_type = sanitize_for_log(match.type)
        safe_feed = sanitize_for_log(ind.source_feed)
        description = (
            f"Threat-intel match: {safe_value} ({safe_type}) from {safe_feed} confidence={clamped}"
        )
        # Cap the value embedded in the dedup key so a pathologically long
        # indicator value (e.g. a 4 KB URL) cannot bloat the unique
        # `alerts.dedup_key` TEXT index. 512 chars leaves headroom for the
        # framing while staying well below SQLite's row-size limits.
        dedup_value = match.value[:_DEDUP_VALUE_MAX_LEN]
        return Alert(
            alert_id=_alert_uuid5(event, match, entity_uuid),
            alert_type="ioc",
            timestamp_ns=event.timestamp_ns,
            severity_id=SeverityLevel(severity),
            rule_name=f"ti:{safe_feed}",
            description=description,
            entity_uuid=entity_uuid,
            entity_value=entity_value,
            entity_type=entity_type,
            contributing_events=(event.event_id,),
            mitre_tactics=tactics,
            mitre_techniques=(),
            risk_score=max(0.0, min(1.0, risk)),
            dedup_key=f"ioc:{match.type}:{dedup_value}:{entity_uuid}",
        )


class IoCEnrichmentMetrics(msgspec.Struct, frozen=True, gc=False):
    """Immutable snapshot of IoC enrichment counters, surfaced via /api/v1/stats."""

    alerts_emitted_total: int = 0
    alerts_deduped_total: int = 0
    dropped_entity_uuid_lookups_total: int = 0
    risk_register_updates_total: int = 0


@dataclass(slots=True)
class _IoCEnrichmentCounters:
    """Mutable counter holder; lives in the handler closure."""

    alerts_emitted_total: int = 0
    alerts_deduped_total: int = 0
    dropped_entity_uuid_lookups_total: int = 0
    risk_register_updates_total: int = 0

    def snapshot(self) -> IoCEnrichmentMetrics:
        return IoCEnrichmentMetrics(
            alerts_emitted_total=self.alerts_emitted_total,
            alerts_deduped_total=self.alerts_deduped_total,
            dropped_entity_uuid_lookups_total=self.dropped_entity_uuid_lookups_total,
            risk_register_updates_total=self.risk_register_updates_total,
        )
