"""Pure prompt builder for Sigma rule suggestion (S-100).

Builds a deterministic instruction prompt that the configured ``LLMBackend``
turns into a drafted Sigma YAML rule. The function has no I/O — the
``Alert`` and ``SeerflowEvent`` instances carry every byte the prompt
needs — so the output is fully testable in isolation.

Char budget defaults to 8000 (~2000 tokens at 4 chars/token) which leaves
headroom for the model's 1024-token completion on a 4096-token context
window backend. Per-field cap (``_FIELD_CHAR_CAP=512``) protects against
a single runaway log line blowing the budget; sample alerts and events are
dropped oldest-first when the assembled prompt still overshoots.

The one-shot example is inlined as a string literal (instead of being
loaded from ``seerflow.sigma.rules``) so the builder stays pure: no file
system access at module import time, no hidden state. The example is a
canonical SigmaHQ skeleton with every load-bearing field the validator
checks (``title``, ``id``, ``status``, ``logsource``, ``detection``,
``condition``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent


# Per-field cap (chars). Mirrors ``seerflow.llm.explanation.prompt`` so
# the two prompt budgets stay aligned.
_FIELD_CHAR_CAP = 512
_TRUNCATE_MARKER = "..."

_DEFAULT_MAX_PROMPT_CHARS = 8000

# Minimum number of samples we always try to keep, even when the budget
# would force us to drop more. One sample is enough for the LLM to infer
# the pattern; dropping below this would leave only structural context.
_MIN_SAMPLES_KEPT = 1


# Canonical SigmaHQ skeleton emitted in the one-shot example. Designed to
# pass ``seerflow.sigma.validator.validate_yaml`` on its own — gives the
# LLM a working template it can adapt rather than a sketch it must complete.
_ONE_SHOT_EXAMPLE = """\
title: SSH brute force from external IP
id: 5e3b14a2-9e9d-4a5b-94f4-c2c5d3e4f1aa
status: experimental
description: Detects repeated failed SSH logins from a single source IP within a short window.
author: Seerflow LLM (drafted from TP feedback)
date: 2026-05-13
logsource:
    category: authentication
    product: linux
    service: sshd
detection:
    selection:
        action: ssh_failed
    condition: selection | count() > 5
falsepositives:
    - Automated security scans
level: medium
"""


_INSTRUCTION = (
    "INSTRUCTION:\n"
    "Draft a Sigma rule in YAML that would deterministically detect the\n"
    "pattern described above. Respond with ONE fenced YAML block and no\n"
    "commentary. Use exactly this format:\n"
    "\n"
    "```yaml\n"
    "title: <short description of the threat>\n"
    "id: <new UUID>\n"
    "status: experimental\n"
    "description: <one sentence>\n"
    "author: Seerflow LLM (drafted from TP feedback)\n"
    "date: <today's UTC date>\n"
    "logsource:\n"
    "    category: <category from the sample events>\n"
    "detection:\n"
    "    selection:\n"
    "        <field>: <value>\n"
    "    condition: selection\n"
    "level: medium\n"
    "```\n"
    "\n"
    "EXAMPLE (do not copy verbatim):\n"
    f"```yaml\n{_ONE_SHOT_EXAMPLE}```\n"
    "\n"
    "Be precise. Do not invent fields beyond the data above. Choose the\n"
    "narrowest selection that still matches every contributing event.\n"
)


def _cap_field(value: str, cap: int = _FIELD_CHAR_CAP) -> str:
    """Truncate ``value`` to ``cap`` characters with a trailing marker."""
    if len(value) <= cap:
        return value
    return value[: max(0, cap - len(_TRUNCATE_MARKER))] + _TRUNCATE_MARKER


def _format_alert(alert: Alert, *, index: int) -> str:
    """Render one TP-confirmed alert as a multi-line block."""
    iso = datetime.fromtimestamp(alert.timestamp_ns / 1_000_000_000, tz=UTC).isoformat(
        timespec="seconds"
    )
    tactics = ",".join(alert.mitre_tactics) if alert.mitre_tactics else "-"
    techniques = ",".join(alert.mitre_techniques) if alert.mitre_techniques else "-"
    description = _cap_field(alert.description)
    return (
        f"ALERT #{index + 1}:\n"
        f"  timestamp_utc={iso}\n"
        f"  alert_type={_cap_field(alert.alert_type, 32)}\n"
        f"  rule_name={_cap_field(alert.rule_name, 128)}\n"
        f"  entity_type={_cap_field(alert.entity_type, 32)}\n"
        f"  entity_value={_cap_field(alert.entity_value, 128)}\n"
        f"  description={description}\n"
        f"  severity={alert.severity_id}\n"
        f"  mitre_tactics={tactics}\n"
        f"  mitre_techniques={techniques}\n"
        f"  risk_score={alert.risk_score:.3f}"
    )


def _format_event(event: SeerflowEvent, *, index: int) -> str:
    """Render one representative contributing event as a multi-line block."""
    iso = datetime.fromtimestamp(event.timestamp_ns / 1_000_000_000, tz=UTC).isoformat(
        timespec="seconds"
    )
    source = _cap_field(event.source_type or "unknown", 64)
    # ``template_id`` is ``int`` (with ``-1`` sentinel for "no template
    # matched"). Render as plain integer; ``-1`` surfaces as "-1" which
    # the LLM can ignore.
    template_id = getattr(event, "template_id", -1)
    template_str_field = _cap_field(getattr(event, "template_str", "") or "-", 128)
    message = _cap_field(event.message or "")
    return (
        f"EVENT #{index + 1}:\n"
        f"  timestamp_utc={iso}\n"
        f"  source_type={source}\n"
        f"  template_id={template_id}\n"
        f"  template_str={template_str_field}\n"
        f"  message={message}"
    )


def _assemble(
    pattern_key: str,
    alert_blocks: tuple[str, ...],
    event_blocks: tuple[str, ...],
) -> str:
    header = (
        "PATTERN:\n"
        f"  pattern_key={pattern_key}\n"
        f"  tp_count={len(alert_blocks)} (each ALERT below has been confirmed "
        f"true-positive by the operator)\n"
    )
    alerts_section = "\n\n".join(alert_blocks) if alert_blocks else "ALERTS: (none recorded)"
    events_section = "\n\n".join(event_blocks) if event_blocks else "EVENTS: (none recorded)"
    return f"{header}\n{alerts_section}\n\n{events_section}\n\n{_INSTRUCTION}"


def build_prompt(
    pattern_key: str,
    sample_alerts: tuple[Alert, ...],
    sample_events: tuple[SeerflowEvent, ...],
    *,
    max_prompt_chars: int = _DEFAULT_MAX_PROMPT_CHARS,
) -> tuple[str, bool]:
    """Build the prompt string and return ``(prompt, truncated)``.

    Args:
        pattern_key: ``"{alert_type}:{rule_name}:{entity_type}"`` for the
            recurring pattern.
        sample_alerts: TP-confirmed alerts ordered newest-first (the
            aggregator's contract). Up to four are used as samples; older
            ones are dropped first when the assembled prompt exceeds
            ``max_prompt_chars``.
        sample_events: Representative contributing events, one per sample
            alert when possible. Same ordering convention.
        max_prompt_chars: Soft ceiling on the assembled prompt size.
            Per-field caps still apply unconditionally; this knob controls
            the sample-dropping behaviour only.

    Returns:
        Tuple ``(prompt, truncated)`` where ``truncated`` is ``True`` if
        any sample alert or event was dropped to fit the budget.
    """
    alerts_kept = list(sample_alerts)
    events_kept = list(sample_events)
    truncated = False

    def _render() -> str:
        alert_blocks = tuple(_format_alert(a, index=i) for i, a in enumerate(alerts_kept))
        event_blocks = tuple(_format_event(e, index=i) for i, e in enumerate(events_kept))
        return _assemble(pattern_key, alert_blocks, event_blocks)

    prompt = _render()
    # Drop oldest sample first; samples are ordered newest-first by the
    # aggregator, so "oldest" is the last element of each list.
    while len(prompt) > max_prompt_chars and (
        len(alerts_kept) > _MIN_SAMPLES_KEPT or len(events_kept) > _MIN_SAMPLES_KEPT
    ):
        truncated = True
        # Drop the longer of the two tails first; if both have a tail,
        # prefer events (they tend to carry the heavier ``message`` field).
        if events_kept and (
            len(events_kept) > len(alerts_kept) or len(alerts_kept) <= _MIN_SAMPLES_KEPT
        ):
            events_kept.pop()
        elif len(alerts_kept) > _MIN_SAMPLES_KEPT:
            alerts_kept.pop()
        else:  # pragma: no cover -- defensive, loop guard already filters
            break
        prompt = _render()

    return prompt, truncated
