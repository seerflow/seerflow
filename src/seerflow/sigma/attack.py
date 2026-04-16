"""MITRE ATT&CK tactic mapping and validation for Sigma rule tags."""

from __future__ import annotations

import re

_TECHNIQUE_PATTERN = re.compile(r"^T\d{4}(?:\.\d{3})?$", re.IGNORECASE)
_TACTIC_ID_PATTERN = re.compile(r"^TA\d{4}$", re.IGNORECASE)

TACTICS: dict[str, str] = {
    "reconnaissance": "Reconnaissance (TA0043)",
    "resource_development": "Resource Development (TA0042)",
    "initial_access": "Initial Access (TA0001)",
    "execution": "Execution (TA0002)",
    "persistence": "Persistence (TA0003)",
    "privilege_escalation": "Privilege Escalation (TA0004)",
    "defense_evasion": "Defense Evasion (TA0005)",
    "credential_access": "Credential Access (TA0006)",
    "discovery": "Discovery (TA0007)",
    "lateral_movement": "Lateral Movement (TA0008)",
    "collection": "Collection (TA0009)",
    "exfiltration": "Exfiltration (TA0010)",
    "command_and_control": "Command and Control (TA0011)",
    "impact": "Impact (TA0040)",
}


# Reverse map from canonical tactic ID (e.g., "TA0003") to tactic name
# (e.g., "persistence"). Mirrors TACTICS; must be updated together.
TACTIC_IDS: dict[str, str] = {
    "TA0043": "reconnaissance",
    "TA0042": "resource_development",
    "TA0001": "initial_access",
    "TA0002": "execution",
    "TA0003": "persistence",
    "TA0004": "privilege_escalation",
    "TA0005": "defense_evasion",
    "TA0006": "credential_access",
    "TA0007": "discovery",
    "TA0008": "lateral_movement",
    "TA0009": "collection",
    "TA0010": "exfiltration",
    "TA0011": "command_and_control",
    "TA0040": "impact",
}


def resolve_tactic(value: str) -> str | None:
    """Return canonical tactic name for a user-supplied value.

    Accepts either a canonical tactic name (e.g., ``"persistence"``)
    or a MITRE tactic ID (e.g., ``"TA0003"``). Matching is
    case-insensitive. Returns ``None`` if the value is neither.
    """
    if not value:
        return None
    lowered = value.lower()
    if lowered in TACTICS:
        return lowered
    if _TACTIC_ID_PATTERN.match(value):
        return TACTIC_IDS.get(value.upper())
    return None


def is_valid_tactic(name: str) -> bool:
    """Check if a tactic name is a known MITRE ATT&CK tactic."""
    return name in TACTICS


def format_tactic(name: str) -> str:
    """Format a tactic name for display.

    Returns the human-readable name with tactic ID (e.g., "Discovery (TA0007)").
    Falls back to the raw name if not in the mapping.
    """
    return TACTICS.get(name, name)


def is_valid_technique(value: str) -> bool:
    """Return True if ``value`` matches the MITRE technique ID pattern."""
    return bool(_TECHNIQUE_PATTERN.match(value))


def format_technique(tid: str) -> str:
    """Normalize a technique ID to uppercase (e.g., "t1033" -> "T1033")."""
    return tid.upper()
