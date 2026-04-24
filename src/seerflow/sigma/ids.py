"""Deterministic rule ID generation for Sigma rules.

Uses ``uuid5(NAMESPACE, "title|category|product|service")`` so the same rule
(semantically) gets the same ID across processes and restarts. If the YAML
defines its own ``id:`` and it parses as a UUID, that value is preferred.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sigma.rule import SigmaRule

# DO NOT CHANGE in production — changing this invalidates every persisted
# enabled-flag override and counter row in ``sigma_rule_state``.
_NAMESPACE_SIGMA_RULE = uuid.UUID("b2c3d4e5-f6a7-8901-bcde-f23456789012")


def compute_rule_id(rule: SigmaRule) -> str:
    """Return a stable UUID string for *rule*.

    Prefers ``rule.id`` when it parses as a UUID; otherwise falls back to
    ``uuid5(NAMESPACE, "title|category|product|service")``.
    """
    if rule.id is not None:
        try:
            return str(uuid.UUID(str(rule.id)))
        except (ValueError, AttributeError):
            pass
    ls = rule.logsource
    name = (
        f"{rule.title or ''}|"
        f"{ls.category or ''}|"
        f"{ls.product or ''}|"
        f"{ls.service or ''}"
    )
    return str(uuid.uuid5(_NAMESPACE_SIGMA_RULE, name))
