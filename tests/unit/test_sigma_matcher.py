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

    def test_compile_normalizes_hyphenated_attack_tactic_tags(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """SigmaHQ tags multi-word tactics with hyphens
        (``attack.command-and-control``) while our canonical map keys them
        with underscores. Such tags must normalize to the canonical
        underscore form and must NOT emit a spurious 'Unknown ATT&CK tactic'
        warning — they are valid MITRE tactics.
        """
        import logging

        rule = SigmaRule.from_yaml("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    message: test
                condition: sel
            level: medium
            tags:
                - attack.command-and-control
                - attack.defense-evasion
                - attack.initial-access
        """)
        seerflow_pipeline().apply(rule)
        with caplog.at_level(logging.WARNING, logger="seerflow.sigma.matcher"):
            cr = compile_rule(rule)

        assert "command_and_control" in cr.attack_tactics
        assert "defense_evasion" in cr.attack_tactics
        assert "initial_access" in cr.attack_tactics
        assert "Unknown ATT&CK tactic" not in caplog.text

    def test_compile_ignores_software_id_tags_without_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """SigmaHQ rules tag the detected tool with a MITRE Software ID
        (e.g. ``attack.s0508`` = Ngrok). Software IDs are neither tactics nor
        techniques and must be ignored silently — not stored as a tactic and
        not warned about as an 'Unknown ATT&CK tactic'.
        """
        import logging

        rule = SigmaRule.from_yaml("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    message: test
                condition: sel
            level: medium
            tags:
                - attack.command_and_control
                - attack.s0508
                - attack.t1071
        """)
        seerflow_pipeline().apply(rule)
        with caplog.at_level(logging.WARNING, logger="seerflow.sigma.matcher"):
            cr = compile_rule(rule)

        assert "s0508" not in cr.attack_tactics
        assert "s0508" not in cr.attack_techniques
        assert "command_and_control" in cr.attack_tactics
        assert "t1071" in cr.attack_techniques
        assert "Unknown ATT&CK tactic" not in caplog.text

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


class TestMatcherCoverage:
    """Additional tests for uncovered branches."""

    def test_wildcard_single_character(self) -> None:
        """WILDCARD_SINGLE (?) should match exactly one character."""
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    CommandLine: "whoam?"
                condition: sel
            level: medium
        """)
        assert match_event(cr, {"message": "whoami"}) is True
        assert match_event(cr, {"message": "whoamX"}) is True
        assert match_event(cr, {"message": "whoam"}) is False

    def test_non_attack_tags_ignored(self) -> None:
        """Tags with namespace != 'attack' should not appear in tactics/techniques."""
        from sigma.rule import SigmaRule

        from seerflow.sigma.matcher import compile_rule

        rule = SigmaRule.from_yaml("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    message: test
                condition: sel
            level: medium
            tags:
                - attack.discovery
                - cve.2021-44228
                - custom.tag
        """)
        from seerflow.sigma.pipeline import seerflow_pipeline

        seerflow_pipeline().apply(rule)
        cr = compile_rule(rule)
        assert "discovery" in cr.attack_tactics
        assert len(cr.attack_techniques) == 0

    def test_numeric_field_value(self) -> None:
        """Integer values (e.g., EventID: 4625) should match via direct equality."""
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    EventID: 4625
                condition: sel
            level: medium
        """)
        assert match_event(cr, {"template_id": 4625}) is True
        assert match_event(cr, {"template_id": 9999}) is False

    def test_keyword_condition(self) -> None:
        """Keyword conditions (no field) should search in message."""
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                keywords:
                    - "error"
                    - "failed"
                condition: keywords
            level: medium
        """)
        assert match_event(cr, {"message": "an error occurred"}) is True
        assert match_event(cr, {"message": "operation failed"}) is True
        assert match_event(cr, {"message": "all good"}) is False

    def test_empty_parsed_conditions(self) -> None:
        """A rule with no parsed conditions should return False."""
        from unittest.mock import MagicMock

        from seerflow.sigma.matcher import CompiledRule

        mock_rule = MagicMock()
        mock_rule.detection.parsed_condition = []
        cr = CompiledRule(
            rule_id="00000000-0000-0000-0000-000000000000",
            rule_name="test",
            description="",
            severity=SeverityLevel.INFORMATIONAL,
            attack_tactics=(),
            attack_techniques=(),
            logsource_key=("", "", ""),
            _rule=mock_rule,
        )
        assert match_event(cr, {"message": "test"}) is False


class TestAttackTagValidation:
    def test_unknown_tactic_logged_as_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unknown ATT&CK tactic names produce a log warning."""
        import logging

        from sigma.rule import SigmaRule

        from seerflow.sigma.matcher import compile_rule
        from seerflow.sigma.pipeline import seerflow_pipeline

        rule = SigmaRule.from_yaml("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    message: test
                condition: sel
            level: medium
            tags:
                - attack.not_a_real_tactic
                - attack.t1033
        """)
        seerflow_pipeline().apply(rule)
        with caplog.at_level(logging.WARNING, logger="seerflow.sigma.matcher"):
            cr = compile_rule(rule)
        assert "not_a_real_tactic" in caplog.text
        assert "not_a_real_tactic" in cr.attack_tactics


def test_compiled_rule_has_rule_id() -> None:
    """S-151: CompiledRule carries a stable UUID rule_id."""
    from sigma.rule import SigmaRule

    from seerflow.sigma.matcher import compile_rule

    rule = SigmaRule.from_yaml(
        """
title: Has ID
logsource: {product: linux, category: process_creation}
detection:
  sel: {Image: '/x'}
  condition: sel
"""
    )
    compiled = compile_rule(rule)
    assert isinstance(compiled.rule_id, str)
    assert len(compiled.rule_id) == 36


class TestSigmaPrecompileCache:
    """S-356: compile_rule caches parsed conditions + pre-warms regexes so the
    per-event match path is a pure cache hit, producing identical decisions."""

    _RULE_YAML = """
        title: Whoami detection
        status: test
        logsource:
            category: process_creation
            product: linux
        detection:
            sel:
                message|contains: whoami
            condition: sel
        level: high
    """

    def test_compile_rule_caches_parsed_conditions(self) -> None:
        """compile_rule must cache the parsed condition nodes so match_event
        does not re-read rule.detection.parsed_condition per event."""
        cr = _make_compiled(self._RULE_YAML)
        assert hasattr(cr, "parsed_conditions")
        assert len(cr.parsed_conditions) >= 1

    def test_precompiled_match_equals_lazy_match(self) -> None:
        """match_event over a precompiled rule yields the same decision the
        lazy path produced (regression guard for the optimization)."""
        cr = _make_compiled(self._RULE_YAML)
        assert match_event(cr, {"message": "bash -c whoami"}) is True
        assert match_event(cr, {"message": "bash -c ls"}) is False


class TestEvalNodeBranchCoverage:
    """S-356: close pre-existing _eval_node branch gaps surfaced by the
    touched-path coverage gate (numeric-value edge paths + keyword non-string)."""

    def test_numeric_value_missing_field_returns_false(self) -> None:
        """A numeric Sigma value against an event missing that field -> False."""
        cr = _make_compiled("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    EventID: 4625
                condition: sel
            level: medium
        """)
        # template_id (the remapped EventID) absent -> _eval_node line 232.
        assert match_event(cr, {"message": "no event id here"}) is False

    def test_numeric_value_in_tuple_field(self) -> None:
        """A numeric Sigma value checked against a tuple field via membership."""
        from sigma.conditions import ConditionFieldEqualsValueExpression

        from seerflow.sigma.matcher import (
            CompiledRule,
            _eval_node,
        )

        # Build a leaf node directly: field is a TUPLE_FIELD, value is numeric.
        node = ConditionFieldEqualsValueExpression("related_ips", 42)
        assert _eval_node(node, {"related_ips": (42, 7)}) is True
        assert _eval_node(node, {"related_ips": (1, 2)}) is False
        assert isinstance(CompiledRule, type)  # import sanity

    def test_keyword_non_string_value(self) -> None:
        """A keyword (ConditionValueExpression) with a non-SigmaString value
        falls back to substring search via str()."""
        from sigma.conditions import ConditionValueExpression

        from seerflow.sigma.matcher import _eval_node

        node = ConditionValueExpression(4625)
        assert _eval_node(node, {"message": "code 4625 seen"}) is True
        assert _eval_node(node, {"message": "nothing here"}) is False
