"""Tests for MITRE ATT&CK tactic mapping and validation."""

from __future__ import annotations

import pytest

from seerflow.sigma.attack import (
    TACTIC_IDS,
    TACTICS,
    format_tactic,
    format_technique,
    is_valid_tactic,
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


@pytest.mark.parametrize("value", ["", "not_a_tactic", "TA9999", "tailgating"])
def test_resolve_tactic_returns_none_for_unknown(value: str) -> None:
    assert resolve_tactic(value) is None
