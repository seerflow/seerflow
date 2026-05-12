"""Unit tests for ``translate_to_event_query`` (S-072, Task 6)."""

from __future__ import annotations

import pytest

from seerflow.llm.hunt._to_event_query import translate_to_event_query
from seerflow.models.query import EventQuery

_DEFAULT_WINDOW_NS = 24 * 3_600 * 1_000_000_000


@pytest.mark.unit
def test_empty_filters_returns_default_window_query() -> None:
    q = translate_to_event_query(
        {},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert isinstance(q, EventQuery)
    assert q.limit == 100
    assert q.time_range is not None
    assert q.time_range.end_ns - q.time_range.start_ns == _DEFAULT_WINDOW_NS


@pytest.mark.unit
def test_iso_time_range_translated_to_ns() -> None:
    filters: dict[str, object] = {
        "time_range_iso": {
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-01T06:00:00Z",
        }
    }
    q = translate_to_event_query(
        filters,
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.time_range is not None
    # 6 hour window in nanoseconds.
    assert q.time_range.end_ns - q.time_range.start_ns == 6 * 3_600 * 1_000_000_000


@pytest.mark.unit
def test_severity_min_passthrough() -> None:
    q = translate_to_event_query(
        {"severity_min": 4},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.severity_min == 4


@pytest.mark.unit
def test_text_query_passthrough() -> None:
    q = translate_to_event_query(
        {"text_query": "ssh"},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.text_query == "ssh"


@pytest.mark.unit
def test_source_type_passthrough() -> None:
    q = translate_to_event_query(
        {"source_type": "auth"},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.source_type == "auth"


@pytest.mark.unit
def test_limit_clamped_to_one_thousand() -> None:
    q = translate_to_event_query(
        {},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=99_999,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.limit == 1000


@pytest.mark.unit
def test_limit_clamped_to_minimum_one() -> None:
    q = translate_to_event_query(
        {},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=0,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.limit == 1


@pytest.mark.unit
def test_invalid_time_range_iso_falls_back_to_default_window() -> None:
    # Parser shouldn't have emitted this, but be defensive: an arbitrary
    # dict that doesn't follow the schema → default window.
    q = translate_to_event_query(
        {"time_range_iso": {"start": "nope"}},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.time_range is not None
    assert q.time_range.end_ns - q.time_range.start_ns == _DEFAULT_WINDOW_NS


@pytest.mark.unit
def test_severity_min_out_of_range_clamped() -> None:
    # Defense in depth — the parser already clamps, but the validator
    # is independently safe.
    q = translate_to_event_query(
        {"severity_min": 99},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.severity_min == 6


@pytest.mark.unit
def test_entity_value_without_entity_type_dropped_to_text_query() -> None:
    """``EventQuery`` indexes by ``entity_uuid``; without resolution we cannot
    use ``entity_value`` directly. The translator promotes it to ``text_query``
    so the filter still has an effect.
    """
    q = translate_to_event_query(
        {"entity_value": "alice"},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    # entity_uuid is unset (we have no UUID resolution here).
    assert q.entity_uuid is None
    # text_query carries the value.
    assert q.text_query == "alice"


@pytest.mark.unit
def test_entity_value_combined_with_existing_text_query() -> None:
    q = translate_to_event_query(
        {"entity_value": "alice", "text_query": "ssh"},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    # text_query wins when both present.
    assert q.text_query == "ssh"


@pytest.mark.unit
def test_severity_min_negative_clamped_to_zero() -> None:
    q = translate_to_event_query(
        {"severity_min": -5},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.severity_min == 0


@pytest.mark.unit
def test_severity_min_boolean_dropped() -> None:
    q = translate_to_event_query(
        {"severity_min": True},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.severity_min is None


@pytest.mark.unit
def test_iso_to_ns_handles_garbage_string() -> None:
    """Invalid ISO strings on either side of the range fall back."""
    q = translate_to_event_query(
        {"time_range_iso": {"start": "2026-01-01T00:00:00Z", "end": "not-a-date"}},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.time_range is not None
    assert q.time_range.end_ns - q.time_range.start_ns == _DEFAULT_WINDOW_NS


@pytest.mark.unit
def test_source_type_whitespace_only_dropped() -> None:
    q = translate_to_event_query(
        {"source_type": "   "},
        default_window_ns=_DEFAULT_WINDOW_NS,
        default_limit=100,
        now_ns=1_700_000_000_000_000_000,
    )
    assert q.source_type is None


@pytest.mark.unit
def test_result_always_passes_event_query_post_init() -> None:
    """Translator must never produce an invalid EventQuery."""
    for filters in [
        {"text_query": "x"},
        {"severity_min": 0},
        {"severity_min": 6},
        {"source_type": "auth"},
        {},
    ]:
        q = translate_to_event_query(
            filters,  # type: ignore[arg-type]
            default_window_ns=_DEFAULT_WINDOW_NS,
            default_limit=100,
            now_ns=1_700_000_000_000_000_000,
        )
        # No exception → __post_init__ passed.
        assert isinstance(q, EventQuery)
