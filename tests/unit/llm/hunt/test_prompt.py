"""Unit tests for the NL-hunt prompt builder (S-072, Task 3)."""

from __future__ import annotations

import pytest

from seerflow.llm.hunt.prompt import build_prompt


@pytest.mark.unit
def test_build_prompt_is_deterministic() -> None:
    a = build_prompt("ssh logins from external")
    b = build_prompt("ssh logins from external")
    assert a == b


@pytest.mark.unit
def test_build_prompt_embeds_user_query() -> None:
    prompt = build_prompt("unusual SSH from external IPs")
    assert "unusual SSH from external IPs" in prompt


@pytest.mark.unit
def test_build_prompt_includes_schema_keys() -> None:
    prompt = build_prompt("anything")
    for key in (
        "time_range_iso",
        "source_type",
        "severity_min",
        "entity_value",
        "entity_type",
        "text_query",
    ):
        assert key in prompt, f"missing schema key: {key}"


@pytest.mark.unit
def test_build_prompt_contains_json_instruction() -> None:
    prompt = build_prompt("anything")
    lower = prompt.lower()
    assert "json" in lower
    # Should mention "only" so the model emits a JSON object alone.
    assert "only" in lower


@pytest.mark.unit
def test_build_prompt_contains_example() -> None:
    prompt = build_prompt("anything")
    # The example contains a "last N hours"-style relative phrase so the
    # model learns to translate it to ISO timestamps.
    assert "EXAMPLE" in prompt.upper() or "example" in prompt
    assert "last" in prompt.lower()


@pytest.mark.unit
def test_build_prompt_caps_overlong_user_query() -> None:
    big = "x" * 2000
    prompt = build_prompt(big, max_query_chars=256)
    # The user query is capped — the full 2000-char blob must not appear.
    assert big not in prompt
    # Truncation marker present.
    assert "..." in prompt


@pytest.mark.unit
def test_build_prompt_short_query_not_truncated() -> None:
    prompt = build_prompt("short", max_query_chars=256)
    assert "short" in prompt
    # No truncation marker injected because input fits the cap.
    capped_segment = prompt.split("QUERY:")[-1]
    assert "..." not in capped_segment.split("INSTRUCTION")[0]


@pytest.mark.unit
def test_build_prompt_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="empty"):
        build_prompt("")


@pytest.mark.unit
def test_build_prompt_rejects_whitespace_only_query() -> None:
    with pytest.raises(ValueError, match="empty"):
        build_prompt("   \n  \t  ")
