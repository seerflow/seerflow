"""Tests for the Sigma detection matcher."""

from __future__ import annotations

import pytest
from sigma.rule import SigmaRule

from seerflow.models.event import SeverityLevel
from seerflow.sigma.matcher import CompiledRule, compile_rule, match_event
from seerflow.sigma.pipeline import seerflow_pipeline


def _make_compiled(yaml_str: str) -> CompiledRule:
    """Helper: parse YAML, apply pipeline, compile."""
    rule = SigmaRule.from_yaml(yaml_str)
    seerflow_pipeline().apply(rule)
    return compile_rule(rule)


class TestCompileRule:
    def test_compile_returns_compiled_rule(self) -> None:
        cr = _make_compiled("""
            title: Test Rule
            status: test
            logsource:
                category: process_creation
                product: linux
            detection:
                sel:
                    CommandLine|contains: whoami
                condition: sel
            level: high
            tags:
                - attack.discovery
                - attack.t1033
        """)
        assert cr.rule_name == "Test Rule"
        assert cr.logsource_key == ("process_creation", "linux", "")

    def test_compile_extracts_attack_tags(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    CommandLine: test
                condition: sel
            level: medium
            tags:
                - attack.discovery
                - attack.t1033
                - attack.lateral_movement
                - attack.t1021.001
        """)
        assert "discovery" in cr.attack_tactics
        assert "t1033" in cr.attack_techniques
        assert "lateral_movement" in cr.attack_tactics
        assert "t1021.001" in cr.attack_techniques

    def test_compile_maps_severity_levels(self) -> None:
        for sigma_level, expected_severity in [
            ("informational", SeverityLevel.INFORMATIONAL),
            ("low", SeverityLevel.NOTICE),
            ("medium", SeverityLevel.WARNING),
            ("high", SeverityLevel.ERROR),
            ("critical", SeverityLevel.CRITICAL),
        ]:
            cr = _make_compiled(f"""
                title: Test
                status: test
                logsource:
                    category: test
                detection:
                    sel:
                        message: test
                    condition: sel
                level: {sigma_level}
            """)
            assert cr.severity == expected_severity, (
                f"Sigma level '{sigma_level}' should map to {expected_severity}"
            )

    def test_compile_empty_logsource(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    message: test
                condition: sel
            level: medium
        """)
        assert cr.logsource_key == ("test", "", "")


class TestMatchEvent:
    def test_simple_string_match(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    message: "failed login"
                condition: sel
            level: medium
        """)
        assert match_event(cr, {"message": "failed login"}) is True
        assert match_event(cr, {"message": "successful login"}) is False

    def test_contains_modifier(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    CommandLine|contains: whoami
                condition: sel
            level: medium
        """)
        assert match_event(cr, {"message": "bash -c whoami"}) is True
        assert match_event(cr, {"message": "bash -c ls"}) is False

    def test_tuple_field_contains(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    User: root
                condition: sel
            level: medium
        """)
        assert match_event(cr, {"related_users": ("root", "admin")}) is True
        assert match_event(cr, {"related_users": ("admin",)}) is False
        assert match_event(cr, {"related_users": ()}) is False

    def test_and_condition(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    CommandLine|contains: whoami
                    User: root
                condition: sel
            level: medium
        """)
        assert match_event(cr, {"message": "whoami", "related_users": ("root",)}) is True
        assert match_event(cr, {"message": "whoami", "related_users": ("admin",)}) is False

    def test_or_condition(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel1:
                    CommandLine|contains: whoami
                sel2:
                    CommandLine|contains: id
                condition: sel1 or sel2
            level: medium
        """)
        assert match_event(cr, {"message": "whoami"}) is True
        assert match_event(cr, {"message": "id"}) is True
        assert match_event(cr, {"message": "ls"}) is False

    def test_not_condition(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    CommandLine|contains: whoami
                filter:
                    User: admin
                condition: sel and not filter
            level: medium
        """)
        assert match_event(cr, {"message": "whoami", "related_users": ("root",)}) is True
        assert match_event(cr, {"message": "whoami", "related_users": ("admin",)}) is False

    def test_missing_field_no_match(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    message: test
                condition: sel
            level: medium
        """)
        assert match_event(cr, {}) is False

    def test_multi_value_or(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    CommandLine|contains:
                        - passwd
                        - shadow
                condition: sel
            level: medium
        """)
        assert match_event(cr, {"message": "cat /etc/passwd"}) is True
        assert match_event(cr, {"message": "cat /etc/shadow"}) is True
        assert match_event(cr, {"message": "cat /etc/hosts"}) is False

    def test_case_insensitive_matching(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    CommandLine|contains: WHOAMI
                condition: sel
            level: medium
        """)
        assert match_event(cr, {"message": "bash -c whoami"}) is True

    def test_compiled_rule_is_frozen(self) -> None:
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    message: test
                condition: sel
            level: medium
        """)
        with pytest.raises(AttributeError):
            cr.rule_name = "changed"  # type: ignore[misc]
