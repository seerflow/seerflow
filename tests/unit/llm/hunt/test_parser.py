"""Unit tests for the NL-hunt response parser (S-072, Task 4)."""

from __future__ import annotations

import pytest

from seerflow.llm.hunt.parser import parse_response


@pytest.mark.unit
def test_clean_json_round_trip() -> None:
    text = '{"text_query": "ssh", "source_type": "auth", "severity_min": 4}'
    filters = parse_response(text, original_query="ssh logins")
    assert filters == {
        "text_query": "ssh",
        "source_type": "auth",
        "severity_min": 4,
    }


@pytest.mark.unit
def test_json_wrapped_in_markdown_fence() -> None:
    text = '```json\n{"text_query": "ssh"}\n```'
    filters = parse_response(text, original_query="x")
    assert filters == {"text_query": "ssh"}


@pytest.mark.unit
def test_json_with_extra_prose() -> None:
    text = 'Sure, here are the filters:\n{"text_query": "ssh"} hope this helps.'
    filters = parse_response(text, original_query="x")
    assert filters == {"text_query": "ssh"}


@pytest.mark.unit
def test_garbage_text_falls_back_to_original_query() -> None:
    filters = parse_response("nope, sorry, I have no idea.", original_query="alpha bravo")
    assert filters == {"text_query": "alpha bravo"}


@pytest.mark.unit
def test_empty_text_falls_back_to_original_query() -> None:
    filters = parse_response("", original_query="alpha")
    assert filters == {"text_query": "alpha"}


@pytest.mark.unit
def test_severity_min_out_of_range_clamped() -> None:
    text = '{"severity_min": 99}'
    filters = parse_response(text, original_query="x")
    assert filters == {"severity_min": 6}


@pytest.mark.unit
def test_severity_min_negative_clamped_to_zero() -> None:
    text = '{"severity_min": -3}'
    filters = parse_response(text, original_query="x")
    assert filters == {"severity_min": 0}


@pytest.mark.unit
def test_severity_min_non_integer_dropped() -> None:
    text = '{"severity_min": "high", "text_query": "ssh"}'
    filters = parse_response(text, original_query="x")
    assert filters == {"text_query": "ssh"}


@pytest.mark.unit
def test_time_range_iso_valid() -> None:
    text = '{"time_range_iso": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T06:00:00Z"}}'
    filters = parse_response(text, original_query="x")
    assert "time_range_iso" in filters
    tr = filters["time_range_iso"]
    assert isinstance(tr, dict)
    assert tr["start"] == "2026-01-01T00:00:00Z"
    assert tr["end"] == "2026-01-01T06:00:00Z"


@pytest.mark.unit
def test_time_range_iso_invalid_dropped() -> None:
    text = (
        '{"time_range_iso": '
        '{"start": "not-a-date", "end": "2026-01-01T06:00:00Z"}, '
        '"text_query": "ssh"}'
    )
    filters = parse_response(text, original_query="x")
    assert "time_range_iso" not in filters
    assert filters["text_query"] == "ssh"


@pytest.mark.unit
def test_time_range_iso_start_after_end_dropped() -> None:
    text = '{"time_range_iso": {"start": "2026-02-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"}}'
    filters = parse_response(text, original_query="orig")
    # Time range dropped → falls back to the original query keyword.
    assert "time_range_iso" not in filters


@pytest.mark.unit
def test_time_range_iso_missing_field_dropped() -> None:
    text = '{"time_range_iso": {"start": "2026-01-01T00:00:00Z"}}'
    filters = parse_response(text, original_query="x")
    assert "time_range_iso" not in filters


@pytest.mark.unit
def test_string_fields_strip_whitespace() -> None:
    text = '{"source_type": "  auth  ", "entity_value": "  alice "}'
    filters = parse_response(text, original_query="x")
    assert filters["source_type"] == "auth"
    assert filters["entity_value"] == "alice"


@pytest.mark.unit
def test_empty_string_fields_dropped() -> None:
    text = '{"source_type": "  ", "text_query": "ssh"}'
    filters = parse_response(text, original_query="x")
    assert "source_type" not in filters
    assert filters["text_query"] == "ssh"


@pytest.mark.unit
def test_unknown_keys_ignored() -> None:
    text = '{"text_query": "ssh", "weird_key": "ignored", "template_id": 99}'
    filters = parse_response(text, original_query="x")
    assert filters == {"text_query": "ssh"}


@pytest.mark.unit
def test_nested_objects_first_extracted() -> None:
    """The parser extracts the first balanced JSON object."""
    text = '{"text_query": {"nested": "value"}, "source_type": "auth"}'
    # Nested object is invalid for text_query → dropped silently.
    filters = parse_response(text, original_query="x")
    assert "text_query" not in filters
    assert filters["source_type"] == "auth"


@pytest.mark.unit
def test_malformed_json_falls_back() -> None:
    text = "{not valid json at all"
    filters = parse_response(text, original_query="alpha")
    assert filters == {"text_query": "alpha"}


@pytest.mark.unit
def test_non_object_json_falls_back() -> None:
    text = "[1, 2, 3]"
    filters = parse_response(text, original_query="alpha")
    assert filters == {"text_query": "alpha"}


@pytest.mark.unit
def test_severity_min_boolean_dropped() -> None:
    text = '{"severity_min": true, "text_query": "ssh"}'
    filters = parse_response(text, original_query="x")
    assert "severity_min" not in filters
    assert filters["text_query"] == "ssh"


@pytest.mark.unit
def test_string_field_with_only_whitespace_dropped() -> None:
    text = '{"entity_type": ""}'
    filters = parse_response(text, original_query="orig")
    assert "entity_type" not in filters


@pytest.mark.unit
def test_time_range_iso_non_dict_dropped() -> None:
    text = '{"time_range_iso": "last 6 hours"}'
    filters = parse_response(text, original_query="x")
    assert "time_range_iso" not in filters


@pytest.mark.unit
def test_escape_inside_string_does_not_break_brace_tracking() -> None:
    """Strings with escaped quotes / backslashes must not unbalance braces."""
    # The string literal contains an escaped quote followed by a brace.
    text = r'{"text_query": "a \"quote\" with } brace"}'
    filters = parse_response(text, original_query="orig")
    assert filters == {"text_query": 'a "quote" with } brace'}


@pytest.mark.unit
def test_leading_lone_close_brace_skipped() -> None:
    """A stray ``}`` before any ``{`` must not start an extraction."""
    text = '} } {"text_query": "ssh"}'
    filters = parse_response(text, original_query="orig")
    assert filters == {"text_query": "ssh"}


@pytest.mark.unit
def test_partially_invalid_json_falls_back() -> None:
    """The extractor finds the first balanced ``{...}`` block but its
    payload is malformed JSON → fall back to text_query."""
    text = '{"text_query": "ssh", invalid_pair}'
    filters = parse_response(text, original_query="orig")
    assert filters == {"text_query": "orig"}


@pytest.mark.unit
def test_backslash_at_start_of_escape_sequence() -> None:
    """Stray backslash followed by other chars exercises the escape branch."""
    text = r'{"text_query": "back\\slash"}'
    filters = parse_response(text, original_query="orig")
    assert filters == {"text_query": "back\\slash"}
