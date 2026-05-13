"""Pure prompt builder for alert explanation (S-071, Task 2).

The builder takes an ``Alert``, an ordered tuple of contributing
``SeerflowEvent`` objects (oldest-first), and an optional
``EntityBaselineContext``, and returns a deterministic prompt string
plus a ``truncated`` flag.

The string targets the local CPU backend's default ``n_ctx=4096``: a
default character budget of 8000 chars (~2000 tokens) leaves ~2000
tokens of headroom for completion. Each individual field is also capped
at ``_FIELD_CHAR_CAP=512`` chars so a single runaway event cannot blow
the prompt budget.

The function has no I/O and is safe to test in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.llm.explanation.context import EntityBaselineContext
    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent


_FIELD_CHAR_CAP = 512
_TRUNCATE_MARKER = "..."

_INSTRUCTION = (
    "INSTRUCTION:\n"
    "Respond using exactly these four section headers, each on its own line:\n"
    "  SUMMARY: <one or two sentences>\n"
    "  RATIONALE: <why this is anomalous>\n"
    "  EVENTS:\n  - <one bullet per contributing event>\n"
    "  NEXT STEPS:\n  - <one bullet per recommended action>\n"
    "Be concise. Do not invent facts beyond the data above."
)


def _cap_field(value: str, cap: int = _FIELD_CHAR_CAP) -> str:
    """Truncate ``value`` to ``cap`` characters, appending a marker."""
    if len(value) <= cap:
        return value
    return value[: max(0, cap - len(_TRUNCATE_MARKER))] + _TRUNCATE_MARKER


def _format_event(event: SeerflowEvent) -> str:
    """Render one event as a single bullet line."""
    iso = datetime.fromtimestamp(event.timestamp_ns / 1_000_000_000, tz=UTC).isoformat(
        timespec="seconds"
    )
    source = _cap_field(event.source_type or "unknown", 64)
    message = _cap_field(event.message or "")
    return f"- [{iso}] source={source} message={message}"


def _format_alert(alert: Alert) -> str:
    tactics = ",".join(alert.mitre_tactics) if alert.mitre_tactics else "-"
    techniques = ",".join(alert.mitre_techniques) if alert.mitre_techniques else "-"
    iso = datetime.fromtimestamp(alert.timestamp_ns / 1_000_000_000, tz=UTC).isoformat(
        timespec="seconds"
    )
    description = _cap_field(alert.description)
    rule_name = _cap_field(alert.rule_name, 128)
    return (
        f"ALERT:\n"
        f"  id={alert.alert_id}\n"
        f"  type={alert.alert_type}\n"
        f"  rule_name={rule_name}\n"
        f"  description={description}\n"
        f"  severity={alert.severity_id}\n"
        f"  timestamp_utc={iso}\n"
        f"  entity_type={alert.entity_type}\n"
        f"  entity_value={_cap_field(alert.entity_value, 128)}\n"
        f"  mitre_tactics={tactics}\n"
        f"  mitre_techniques={techniques}\n"
        f"  risk_score={alert.risk_score:.3f}"
    )


def _format_entity_context(context: EntityBaselineContext | None) -> str:
    if context is None or context.baseline_summary is None:
        return "ENTITY CONTEXT: (no baseline)"
    summary = _cap_field(context.baseline_summary)
    return (
        f"ENTITY CONTEXT:\n"
        f"  entity={context.entity_value} ({context.entity_type})\n"
        f"  baseline={summary}"
    )


def _format_events_section(events: tuple[SeerflowEvent, ...]) -> str:
    if not events:
        return "CONTRIBUTING EVENTS: (none recorded)"
    lines = "\n".join(_format_event(e) for e in events)
    return f"CONTRIBUTING EVENTS:\n{lines}"


def _assemble(
    alert_block: str,
    events_block: str,
    context_block: str,
) -> str:
    return f"{alert_block}\n\n{events_block}\n\n{context_block}\n\n{_INSTRUCTION}"


def build_prompt(
    alert: Alert,
    events: tuple[SeerflowEvent, ...],
    entity_context: EntityBaselineContext | None,
    *,
    max_prompt_chars: int = 8000,
) -> tuple[str, bool]:
    """Build the prompt string and return ``(prompt, truncated)``.

    When the assembled prompt would exceed ``max_prompt_chars``, the
    builder drops contributing events oldest-first until the prompt fits
    and sets ``truncated=True``. Per-field caps (``_FIELD_CHAR_CAP``)
    are applied unconditionally to bound a single malicious / runaway
    field.

    The function is pure and deterministic: given the same inputs, the
    same string is returned.
    """
    alert_block = _format_alert(alert)
    context_block = _format_entity_context(entity_context)
    truncated = False
    kept = list(events)
    prompt = _assemble(alert_block, _format_events_section(tuple(kept)), context_block)
    while len(prompt) > max_prompt_chars and kept:
        # Drop the oldest event (events are ordered oldest-first).
        kept.pop(0)
        truncated = True
        prompt = _assemble(alert_block, _format_events_section(tuple(kept)), context_block)
    return prompt, truncated
