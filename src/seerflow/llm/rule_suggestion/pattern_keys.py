"""Pure pattern-key derivation for the rule-suggestion service.

The pattern key is the aggregation key used by ``aggregate_tp_feedback`` to
collapse TP feedback across distinct entity values that share the same
``(alert_type, rule_name, entity_type)`` triple. By excluding the
``entity_value``, three TPs against three different IPs (the canonical
"recurring ML anomaly worth codifying") count as one pattern instead of
three.

The function is pure (no I/O) and deterministic: given the same input
fields, the same key string is returned. Characters outside the
``[a-z0-9_.-]`` set are collapsed to ``-`` so the resulting key is safe to
embed in a URL path (constrained server-side via the
``^[a-z0-9_:.-]{1,128}$`` regex on the FastAPI ``Path`` parameter).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.models.alert import Alert

# Any character outside this set is collapsed to ``-``. The set deliberately
# omits ``:`` because the joiner reserves it as the structural separator
# between the three pattern fields; a literal ``:`` inside a field is
# therefore sanitised, preserving the invariant that
# ``derive_pattern_key(alert).count(":") == 2``.
_SAFE_CHAR_RE = re.compile(r"[^a-z0-9_.-]")


def _sanitise(value: str) -> str:
    """Lower-case, strip, and collapse non-safe characters to ``-``.

    Pure helper; never raises. The caller (``derive_pattern_key``) is
    responsible for treating an empty result as a programming error.
    """
    return _SAFE_CHAR_RE.sub("-", value.strip().lower())


def derive_pattern_key(alert: Alert) -> str:
    """Return the aggregation key ``"{alert_type}:{rule_name}:{entity_type}"``.

    Args:
        alert: Any ``Alert`` instance (ML, Sigma, correlation, UEBA, IoC).

    Returns:
        Lower-cased, colon-joined triple. Every character outside
        ``[a-z0-9_.-]`` in any input field is collapsed to ``-`` so the key
        is safe to embed in a URL path.

    Raises:
        ValueError: when ``rule_name`` is empty or whitespace-only after
            sanitisation. ``alert_type`` and ``entity_type`` are Literal
            types in ``seerflow.models._types`` and cannot be empty at
            this layer; ``rule_name`` is free-form text and must be
            explicit.
    """
    # ``rule_name`` is the only free-form field; the other two come from
    # closed Literal enums and are always non-empty at the model layer.
    rule_name = alert.rule_name.strip()
    if not rule_name:
        msg = "rule_name must be non-empty"
        raise ValueError(msg)

    parts = (
        _sanitise(alert.alert_type),
        _sanitise(alert.rule_name),
        _sanitise(alert.entity_type),
    )
    return ":".join(parts)
