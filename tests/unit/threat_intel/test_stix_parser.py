"""Fixture-driven tests for STIXIndicatorParser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from seerflow.threat_intel.stix_parser import STIXIndicatorParser

if TYPE_CHECKING:
    from seerflow.models.indicator import Indicator

FIXTURES = Path(__file__).parents[2] / "fixtures" / "taxii"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize(
    ("fixture", "expected_type", "expected_value"),
    [
        ("indicator_ipv4.json", "ipv4", "203.0.113.42"),
        ("indicator_ipv6.json", "ipv6", "2001:db8::1"),
        ("indicator_domain.json", "domain", "evil.example"),
        ("indicator_url.json", "url", "http://evil.example/payload"),
    ],
)
def test_parser_extracts_single_observable(
    fixture: str, expected_type: str, expected_value: str
) -> None:
    parser = STIXIndicatorParser()
    out = parser.parse(_load(fixture), source_feed="test")
    assert len(out) == 1
    assert out[0].type == expected_type
    assert out[0].value == expected_value
    assert out[0].source_feed == "test"


@pytest.mark.parametrize(
    ("fixture", "expected_type"),
    [
        ("indicator_md5.json", "md5"),
        ("indicator_sha1.json", "sha1"),
        ("indicator_sha256.json", "sha256"),
    ],
)
def test_parser_extracts_file_hashes(fixture: str, expected_type: str) -> None:
    parser = STIXIndicatorParser()
    out = parser.parse(_load(fixture), source_feed="test")
    assert len(out) == 1
    assert out[0].type == expected_type


def test_parser_handles_composite_pattern() -> None:
    parser = STIXIndicatorParser()
    out = parser.parse(_load("indicator_composite.json"), source_feed="test")
    types = {ind.type for ind in out}
    assert types == {"ipv4", "url"}


def test_parser_handles_qualifier_pattern() -> None:
    parser = STIXIndicatorParser()
    out = parser.parse(_load("indicator_qualifier.json"), source_feed="test")
    assert len(out) == 1
    assert out[0].type == "ipv4"


def test_parser_skips_invalid_pattern_without_raising() -> None:
    parser = STIXIndicatorParser()
    out = parser.parse(_load("indicator_invalid_pattern.json"), source_feed="test")
    assert out == ()


def test_parser_rejects_oversized_pattern() -> None:
    parser = STIXIndicatorParser()
    out = parser.parse(_load("indicator_oversized.json"), source_feed="test")
    assert out == ()


def test_parser_minimal_indicator_uses_defaults() -> None:
    parser = STIXIndicatorParser()
    out = parser.parse(_load("indicator_minimal.json"), source_feed="test")
    assert len(out) == 1
    ind: Indicator = out[0]
    assert ind.confidence == 0
    assert ind.kill_chain_phases == ()
    assert ind.valid_until_ns is None


def test_parser_skips_non_indicator_sdo() -> None:
    parser = STIXIndicatorParser()
    out = parser.parse({"type": "malware", "id": "malware--x"}, source_feed="test")
    assert out == ()
