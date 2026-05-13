"""Unit tests for the STIX phase → MITRE tactic mapping (S-069)."""

from __future__ import annotations

import pytest

from seerflow.threat_intel.enricher import _stix_phases_to_tactics


@pytest.mark.unit
class TestStixPhasesToTactics:
    def test_empty_input_returns_empty_tuple(self) -> None:
        assert _stix_phases_to_tactics(()) == ()

    @pytest.mark.parametrize(
        ("phase", "expected_tactic"),
        [
            ("reconnaissance", "TA0043"),
            ("resource-development", "TA0042"),
            ("initial-access", "TA0001"),
            ("execution", "TA0002"),
            ("persistence", "TA0003"),
            ("privilege-escalation", "TA0004"),
            ("defense-evasion", "TA0005"),
            ("credential-access", "TA0006"),
            ("discovery", "TA0007"),
            ("lateral-movement", "TA0008"),
            ("collection", "TA0009"),
            ("command-and-control", "TA0011"),
            ("exfiltration", "TA0010"),
            ("impact", "TA0040"),
        ],
    )
    def test_each_enterprise_tactic_maps(self, phase: str, expected_tactic: str) -> None:
        assert _stix_phases_to_tactics((phase,)) == (expected_tactic,)

    def test_unknown_phase_is_ignored(self) -> None:
        assert _stix_phases_to_tactics(("weaponization", "delivery", "not-a-phase")) == ()

    def test_phase_normalisation(self) -> None:
        assert _stix_phases_to_tactics(("Initial-Access",)) == ("TA0001",)
        assert _stix_phases_to_tactics(("initial_access",)) == ("TA0001",)
        assert _stix_phases_to_tactics(("  initial-access  ",)) == ("TA0001",)

    def test_dedups_while_preserving_order(self) -> None:
        out = _stix_phases_to_tactics(
            ("execution", "initial-access", "execution", "command-and-control"),
        )
        assert out == ("TA0002", "TA0001", "TA0011")
