"""Tests for layered Sigma YAML validator (S-151)."""

from __future__ import annotations

import pytest

from seerflow.sigma.validator import SigmaRuleValidationError, validate_yaml

_VALID = """
title: Valid Rule
logsource:
  product: linux
  category: process_creation
detection:
  selection:
    Image|endswith: '/whoami'
  condition: selection
"""

_INVALID_YAML = "title: x\n  bad indent: ["
_MISSING_FIELDS = "title: NoLogsource\n"


def test_validate_yaml_returns_rule_for_valid() -> None:
    rule = validate_yaml(_VALID)
    assert rule.title == "Valid Rule"


def test_validate_yaml_yaml_error_carries_line() -> None:
    with pytest.raises(SigmaRuleValidationError) as exc:
        validate_yaml(_INVALID_YAML)
    assert exc.value.stage == "yaml"
    assert exc.value.line is not None
    assert exc.value.line >= 1


def test_validate_yaml_schema_error_has_stage() -> None:
    with pytest.raises(SigmaRuleValidationError) as exc:
        validate_yaml(_MISSING_FIELDS)
    assert exc.value.stage in {"schema", "compile"}


def test_validation_error_str_formats_location() -> None:
    err = SigmaRuleValidationError(stage="yaml", message="bad", line=3, column=7)
    rendered = str(err)
    assert "line 3" in rendered
    assert "col 7" in rendered
    assert "yaml" in rendered
