"""Tests for MITRE ATT&CK tactic mapping and validation."""

from __future__ import annotations

import pytest

from seerflow.sigma.attack import (
    TACTIC_IDS,
    TACTICS,
    format_tactic,
    format_technique,
    is_valid_tactic,
    parent_technique,
    resolve_tactic,
)


class TestTacticsMapping:
    def test_all_14_tactics_present(self) -> None:
        assert len(TACTICS) == 14

    def test_discovery_tactic(self) -> None:
        assert "discovery" in TACTICS
        assert "TA0007" in TACTICS["discovery"]

    def test_execution_tactic(self) -> None:
        assert "execution" in TACTICS
        assert "TA0002" in TACTICS["execution"]


class TestIsValidTactic:
    def test_valid_tactic(self) -> None:
        assert is_valid_tactic("discovery") is True

    def test_invalid_tactic(self) -> None:
        assert is_valid_tactic("not_a_tactic") is False

    def test_case_sensitive(self) -> None:
        assert is_valid_tactic("Discovery") is False


class TestFormatTactic:
    def test_known_tactic(self) -> None:
        assert format_tactic("discovery") == "Discovery (TA0007)"

    def test_unknown_tactic_returns_raw(self) -> None:
        assert format_tactic("unknown_tactic") == "unknown_tactic"

    def test_credential_access(self) -> None:
        assert format_tactic("credential_access") == "Credential Access (TA0006)"


class TestFormatTechnique:
    def test_lowercase_to_uppercase(self) -> None:
        assert format_technique("t1033") == "T1033"

    def test_subtechnique(self) -> None:
        assert format_technique("t1021.001") == "T1021.001"

    def test_already_uppercase(self) -> None:
        assert format_technique("T1059") == "T1059"


def test_tactic_ids_reverse_maps_every_tactic_name() -> None:
    for tactic_id, name in TACTIC_IDS.items():
        assert name in TACTICS, f"{tactic_id} -> {name!r} not in TACTICS"
    assert set(TACTIC_IDS.values()) == set(TACTICS)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("persistence", "persistence"),
        ("Persistence", "persistence"),
        ("TA0003", "persistence"),
        ("ta0003", "persistence"),
        ("discovery", "discovery"),
        ("TA0007", "discovery"),
    ],
)
def test_resolve_tactic_accepts_name_and_id_case_insensitive(value: str, expected: str) -> None:
    assert resolve_tactic(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("command-and-control", "command_and_control"),
        ("Command-And-Control", "command_and_control"),
        ("defense-evasion", "defense_evasion"),
        ("initial-access", "initial_access"),
        ("lateral-movement", "lateral_movement"),
    ],
)
def test_resolve_tactic_normalizes_hyphenated_sigmahq_form(value: str, expected: str) -> None:
    """SigmaHQ writes multi-word tactics with hyphens; resolve_tactic must
    accept that form (used by ``--tactic`` and the REST API) and return the
    canonical underscore name."""
    assert resolve_tactic(value) == expected


@pytest.mark.parametrize("value", ["", "not_a_tactic", "TA9999", "tailgating"])
def test_resolve_tactic_returns_none_for_unknown(value: str) -> None:
    assert resolve_tactic(value) is None


class TestParentTechnique:
    def test_subtechnique_returns_parent(self) -> None:
        assert parent_technique("T1053.005") == "T1053"

    def test_parent_returns_self(self) -> None:
        assert parent_technique("T1053") == "T1053"

    def test_lowercase_subtechnique_normalized(self) -> None:
        assert parent_technique("t1053.005") == "T1053"

    def test_lowercase_parent_normalized(self) -> None:
        assert parent_technique("t1053") == "T1053"

    def test_invalid_input_returned_unchanged(self) -> None:
        assert parent_technique("garbage") == "garbage"

    def test_empty_input_returned_unchanged(self) -> None:
        assert parent_technique("") == ""

    def test_three_digit_subtechnique_suffix(self) -> None:
        assert parent_technique("T1059.003") == "T1059"
