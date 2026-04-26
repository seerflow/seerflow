"""Unit tests for Sigma rule API schemas (S-151)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from seerflow.api.schemas import (
    PaginatedResponse,
    SigmaRuleDetail,
    SigmaRuleSummary,
    SigmaRuleToggleRequest,
    SigmaRuleUploadRequest,
    SigmaRuleValidationResult,
)


def test_rule_summary_required_fields() -> None:
    s = SigmaRuleSummary(
        rule_id="r1",
        title="T",
        severity=3,
        logsource_key=["", "linux", ""],
        attack_tactics=[],
        attack_techniques=[],
        enabled=True,
        source="bundled",
        match_count_lifetime=0,
        last_fired_ns=None,
        alert_count_24h=0,
    )
    assert s.rule_id == "r1"


def test_rule_detail_requires_yaml_source() -> None:
    with pytest.raises(ValidationError):
        SigmaRuleDetail(
            rule_id="r1",
            title="T",
            severity=3,
            logsource_key=["", "linux", ""],
            attack_tactics=[],
            attack_techniques=[],
            enabled=True,
            source="bundled",
            match_count_lifetime=0,
        )  # type: ignore[call-arg]


def test_toggle_request() -> None:
    assert SigmaRuleToggleRequest(enabled=False).enabled is False


def test_upload_request_caps_size() -> None:
    with pytest.raises(ValidationError):
        SigmaRuleUploadRequest(yaml="x" * 65_537)


def test_validation_result_invalid_shape() -> None:
    r = SigmaRuleValidationResult(valid=False, stage="yaml", message="bad", line=2, column=5)
    assert r.line == 2


def test_validation_result_valid_shape() -> None:
    r = SigmaRuleValidationResult(
        valid=True, rule_id="r", title="T", logsource_key=["", "linux", ""]
    )
    assert r.valid is True


def test_list_response_shape() -> None:
    r = PaginatedResponse[SigmaRuleSummary](items=[], total=0, page=1, limit=100, has_next=False)
    assert r.total == 0
    assert r.has_next is False
