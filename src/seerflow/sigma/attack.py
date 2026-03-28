"""MITRE ATT&CK tactic mapping and validation for Sigma rule tags."""

from __future__ import annotations

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


def is_valid_tactic(name: str) -> bool:
    """Check if a tactic name is a known MITRE ATT&CK tactic."""
    return name in TACTICS


def format_tactic(name: str) -> str:
    """Format a tactic name for display.

    Returns the human-readable name with tactic ID (e.g., "Discovery (TA0007)").
    Falls back to the raw name if not in the mapping.
    """
    return TACTICS.get(name, name)


def format_technique(tid: str) -> str:
    """Normalize a technique ID to uppercase (e.g., "t1033" -> "T1033")."""
    return tid.upper()
