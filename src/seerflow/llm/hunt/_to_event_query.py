"""Pure validator: translate filter dict to ``EventQuery`` (S-072, Task 6).

The parser produces a dict whose keys map to ``EventQuery`` fields with
small additional steps:

- ``time_range_iso`` (ISO strings) → ``TimeRange`` (nanoseconds)
- ``entity_value`` (when present without resolution) → promoted to
  ``text_query`` so the filter still has an effect.
- ``limit`` is always clamped to the ``EventQuery`` valid range [1, 1000].
- Missing time range → fall back to a default window ending at ``now_ns``.

The function is pure (no I/O) and never raises — its job is to absorb
malformed translator output and return a runnable ``EventQuery``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from seerflow.models.query import EventQuery, TimeRange

_EVENT_QUERY_LIMIT_MIN = 1
_EVENT_QUERY_LIMIT_MAX = 1000
_SEVERITY_MIN = 0
_SEVERITY_MAX = 6


def _clamp_limit(value: int) -> int:
    if value < _EVENT_QUERY_LIMIT_MIN:
        return _EVENT_QUERY_LIMIT_MIN
    if value > _EVENT_QUERY_LIMIT_MAX:
        return _EVENT_QUERY_LIMIT_MAX
    return value


def _iso_to_ns(iso_value: str) -> int | None:
    try:
        normalised = iso_value.replace("Z", "+00:00") if iso_value.endswith("Z") else iso_value
        dt = datetime.fromisoformat(normalised)
    except (ValueError, TypeError):
        return None
    # Naive datetimes from the LLM are assumed UTC — never local time. Without
    # this normalisation ``.timestamp()`` would interpret naive values in the
    # process's local timezone, producing off-by-hours filter windows.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1_000_000_000)


def _build_time_range(
    filters: dict[str, object],
    *,
    default_window_ns: int,
    now_ns: int,
) -> TimeRange:
    tr_value = filters.get("time_range_iso")
    if isinstance(tr_value, dict):
        start_raw = tr_value.get("start")
        end_raw = tr_value.get("end")
        if isinstance(start_raw, str) and isinstance(end_raw, str):
            start_ns = _iso_to_ns(start_raw)
            end_ns = _iso_to_ns(end_raw)
            if start_ns is not None and end_ns is not None and start_ns <= end_ns:
                return TimeRange(start_ns=start_ns, end_ns=end_ns)
    return TimeRange(start_ns=now_ns - default_window_ns, end_ns=now_ns)


def _clamp_severity(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    if value < _SEVERITY_MIN:
        return _SEVERITY_MIN
    if value > _SEVERITY_MAX:
        return _SEVERITY_MAX
    return value


def _coerce_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def translate_to_event_query(
    filters: dict[str, object],
    *,
    default_window_ns: int,
    default_limit: int,
    now_ns: int,
) -> EventQuery:
    """Convert a translator-output filter dict to an ``EventQuery``.

    Args:
        filters: Output of ``parse_response`` (or any dict shaped like it).
        default_window_ns: Window applied when no time range is present.
        default_limit: Page size; clamped to [1, 1000].
        now_ns: Nanosecond timestamp used as the end of the default window.

    Returns:
        A valid ``EventQuery`` (passes ``__post_init__``).
    """
    time_range = _build_time_range(filters, default_window_ns=default_window_ns, now_ns=now_ns)

    severity_min = _clamp_severity(filters.get("severity_min"))
    source_type = _coerce_string(filters.get("source_type"))
    text_query = _coerce_string(filters.get("text_query"))
    if text_query is None:
        # Promote entity_value to text_query when no other keyword is
        # present — without UUID resolution we can't index by entity.
        entity_value = _coerce_string(filters.get("entity_value"))
        if entity_value is not None:
            text_query = entity_value

    limit = _clamp_limit(default_limit)

    return EventQuery(
        time_range=time_range,
        source_type=source_type,
        severity_min=severity_min,
        template_id=None,
        entity_uuid=None,
        text_query=text_query,
        page=1,
        limit=limit,
    )
