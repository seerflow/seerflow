"""Tests for MITRE ATT&CK template-to-tactic mapping."""

from __future__ import annotations

import pytest


class TestAttackMapper:
    def test_lookup_returns_match(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper, AttackMapping

        mapper = AttackMapper(
            [
                AttackMapping.from_raw(
                    pattern="ssh.*failed",
                    tactics=["credential-access"],
                    techniques=["T1110"],
                )
            ]
        )
        tactics, techniques = mapper.lookup("sshd error: maximum authentication failed for user")
        assert tactics == ("credential-access",)
        assert techniques == ("T1110",)

    def test_lookup_returns_empty_on_no_match(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper, AttackMapping

        mapper = AttackMapper(
            [
                AttackMapping.from_raw(
                    pattern="ssh.*failed",
                    tactics=["credential-access"],
                    techniques=["T1110"],
                )
            ]
        )
        tactics, techniques = mapper.lookup("normal log message about disk usage")
        assert tactics == ()
        assert techniques == ()

    def test_lookup_returns_first_match(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper, AttackMapping

        mapper = AttackMapper(
            [
                AttackMapping.from_raw(
                    pattern="ssh",
                    tactics=["initial-access"],
                    techniques=["T1078"],
                ),
                AttackMapping.from_raw(
                    pattern="ssh.*failed",
                    tactics=["credential-access"],
                    techniques=["T1110"],
                ),
            ]
        )
        tactics, _ = mapper.lookup("ssh failed login")
        assert tactics == ("initial-access",)

    def test_empty_mapper_returns_empty(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper([])
        assert mapper.lookup("anything") == ((), ())

    def test_from_config_parses_raw_dicts(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        raw = [
            {
                "pattern": "sudo.*incorrect",
                "tactics": ["privilege-escalation"],
                "techniques": ["T1548"],
            }
        ]
        mapper = AttackMapper.from_config(raw)
        tactics, _techniques = mapper.lookup("sudo: 3 incorrect password attempts")
        assert tactics == ("privilege-escalation",)

    def test_from_config_raises_on_invalid_regex(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        with pytest.raises(ValueError, match="Invalid regex"):
            AttackMapper.from_config(
                [{"pattern": "[invalid", "tactics": ["x"], "techniques": ["T1"]}]
            )

    def test_case_insensitive_matching(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper, AttackMapping

        mapper = AttackMapper(
            [
                AttackMapping.from_raw(
                    pattern="SSH.*FAILED",
                    tactics=["credential-access"],
                    techniques=["T1110"],
                )
            ]
        )
        tactics, _ = mapper.lookup("ssh connection failed")
        assert tactics == ("credential-access",)


class TestLoadDefaults:
    def test_load_defaults_returns_non_empty_mapper(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper.load_defaults()
        assert len(mapper) >= 5

    def test_default_matches_ssh_brute_force(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper.load_defaults()
        tactics, techniques = mapper.lookup(
            "error: maximum authentication attempts exceeded for user admin from 10.0.0.1"
        )
        assert "credential-access" in tactics
        assert "T1110" in techniques

    def test_default_matches_sudo_failure(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper.load_defaults()
        tactics, _ = mapper.lookup("sudo: 3 incorrect password attempts")
        assert "privilege-escalation" in tactics

    def test_default_matches_segfault(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper.load_defaults()
        tactics, _ = mapper.lookup("segfault at 0x0000 in /usr/bin/app")
        assert "execution" in tactics

    def test_default_no_match_normal_log(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper.load_defaults()
        tactics, techniques = mapper.lookup("INFO: server started on port 8080")
        assert tactics == ()
        assert techniques == ()
