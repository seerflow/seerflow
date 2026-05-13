"""Unit tests for ``seerflow.llm.rule_suggestion.pattern_keys``.

Covers AC1: deterministic, lowercased, sanitised pattern key derivation
from an ``Alert`` instance. The pattern key is the aggregation key used by
the rule-suggestion service to count TP feedback across recurring ML-detected
anomalies that share ``(alert_type, rule_name, entity_type)`` regardless of
``entity_value``.
"""

from __future__ import annotations

import re
import uuid

import pytest

from seerflow.llm.rule_suggestion.pattern_keys import derive_pattern_key
from seerflow.models.alert import Alert

_PATTERN_KEY_RE = re.compile(r"^[a-z0-9_:.-]+$")


def _make_alert(
    *,
    alert_type: str = "ml",
    rule_name: str = "hst-anomaly",
    entity_type: str = "ip",
    entity_value: str = "192.168.1.10",
) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "test")),
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=5,
        rule_name=rule_name,
        description="",
        entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, entity_value)),
        entity_value=entity_value,
        entity_type=entity_type,  # type: ignore[arg-type]
        contributing_events=(),
    )


class TestDerivePatternKey:
    def test_lowercased_colon_joined(self) -> None:
        """AC1: standard ML anomaly alert yields the canonical pattern."""
        alert = _make_alert()
        assert derive_pattern_key(alert) == "ml:hst-anomaly:ip"

    def test_idempotent_under_casing(self) -> None:
        """AC1: casing in input fields is normalised to lower case."""
        upper_alert = _make_alert(
            alert_type="ml",  # AlertType is Literal, can't actually upper
            rule_name="HST-Anomaly",
            entity_type="ip",
        )
        lower_alert = _make_alert(rule_name="hst-anomaly")
        assert derive_pattern_key(upper_alert) == derive_pattern_key(lower_alert)
        assert derive_pattern_key(upper_alert) == "ml:hst-anomaly:ip"

    def test_special_chars_collapsed_to_dash(self) -> None:
        """AC1: non-``[a-z0-9_.-]`` characters in any field become ``-``."""
        alert = _make_alert(rule_name="rule with spaces and !chars")
        key = derive_pattern_key(alert)
        # "rule with spaces and !chars" -> "rule-with-spaces-and--chars"
        # Spaces -> '-'; '!' -> '-'; double dash preserved (no collapsing).
        assert key == "ml:rule-with-spaces-and--chars:ip"

    def test_colon_in_rule_name_sanitised(self) -> None:
        """AC1: a colon in ``rule_name`` must not produce a four-part key."""
        alert = _make_alert(rule_name="some:rule")
        key = derive_pattern_key(alert)
        assert key.count(":") == 2  # only the two structural separators
        assert key == "ml:some-rule:ip"

    def test_output_matches_path_regex(self) -> None:
        """AC1: every output matches the FastAPI path regex."""
        alerts = [
            _make_alert(),
            _make_alert(rule_name="Custom Rule_Name v1.0"),
            _make_alert(rule_name="weird/path?stuff"),
        ]
        for alert in alerts:
            key = derive_pattern_key(alert)
            assert _PATTERN_KEY_RE.fullmatch(key) is not None, key

    def test_empty_rule_name_raises(self) -> None:
        """AC1: empty ``rule_name`` is a programming error, not an empty key."""
        alert = _make_alert(rule_name="")
        with pytest.raises(ValueError, match="rule_name must be non-empty"):
            derive_pattern_key(alert)

    def test_whitespace_only_rule_name_raises(self) -> None:
        """AC1: pure-whitespace ``rule_name`` is treated as empty."""
        alert = _make_alert(rule_name="   \t  ")
        with pytest.raises(ValueError, match="rule_name must be non-empty"):
            derive_pattern_key(alert)

    def test_leading_trailing_whitespace_trimmed(self) -> None:
        """AC1: leading/trailing whitespace does not bleed into the key."""
        alert = _make_alert(rule_name="  hst-anomaly  ")
        assert derive_pattern_key(alert) == "ml:hst-anomaly:ip"

    def test_underscores_and_dots_preserved(self) -> None:
        """AC1: ``_`` and ``.`` survive sanitisation (valid SigmaHQ chars)."""
        alert = _make_alert(rule_name="rule_v1.0")
        assert derive_pattern_key(alert) == "ml:rule_v1.0:ip"
