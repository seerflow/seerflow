"""Tests for deterministic Sigma rule ID generation (S-151)."""

from __future__ import annotations

from sigma.rule import SigmaRule

from seerflow.sigma.ids import compute_rule_id

_VALID_YAML = """
title: Suspicious Whoami Execution
logsource:
  product: linux
  category: process_creation
detection:
  selection:
    Image|endswith: '/whoami'
  condition: selection
"""


def test_compute_rule_id_is_uuid_v5_and_stable() -> None:
    rule = SigmaRule.from_yaml(_VALID_YAML)
    assert compute_rule_id(rule) == compute_rule_id(rule)
    assert len(compute_rule_id(rule)) == 36


def test_compute_rule_id_uses_yaml_id_when_uuid() -> None:
    yaml_with_id = _VALID_YAML.replace(
        "title:",
        "id: 11111111-1111-1111-1111-111111111111\ntitle:",
    )
    rule = SigmaRule.from_yaml(yaml_with_id)
    assert compute_rule_id(rule) == "11111111-1111-1111-1111-111111111111"


def test_compute_rule_id_differs_on_logsource_change() -> None:
    other = _VALID_YAML.replace("product: linux", "product: windows")
    a = compute_rule_id(SigmaRule.from_yaml(_VALID_YAML))
    b = compute_rule_id(SigmaRule.from_yaml(other))
    assert a != b


def test_compute_rule_id_differs_on_title_change() -> None:
    other = _VALID_YAML.replace("Suspicious Whoami", "Different Rule Name")
    a = compute_rule_id(SigmaRule.from_yaml(_VALID_YAML))
    b = compute_rule_id(SigmaRule.from_yaml(other))
    assert a != b
