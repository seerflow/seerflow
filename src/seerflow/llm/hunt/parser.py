"""Lenient JSON parser for the NL hunt translator response (S-072, Task 4).

The LLM is asked (via the prompt's INSTRUCTION block) to emit a single JSON
object naming the structured filters; in practice small CPU models frequently
add prose, wrap the JSON in code fences, or mis-type values. This parser
extracts the first balanced ``{...}`` block, ``json.loads`` it, and validates
each known key independently:

- ``severity_min`` is coerced to an integer and clamped to [0, 6].
- ``time_range_iso`` must be a dict with ISO-8601 ``start`` <= ``end``;
  otherwise dropped.
- String fields are stripped; empty strings are dropped.
- Unknown keys are ignored.

On any failure (missing JSON, malformed JSON, non-object JSON) the parser
returns ``{"text_query": original_query}`` so the orchestrator always has a
usable filter set.

Pure function; no I/O.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

_STRING_FIELDS = ("source_type", "entity_value", "entity_type", "text_query")
_SEVERITY_MIN = 0
_SEVERITY_MAX = 6


def _extract_first_object(text: str) -> str | None:
    """Return the substring of the first balanced ``{...}`` block in ``text``.

    Tracks brace depth, ignoring braces inside string literals. Returns
    ``None`` if no balanced object is found.
    """
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
            continue
        if ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start : i + 1]
    return None


def _parse_iso(value: str) -> datetime | None:
    try:
        # ``datetime.fromisoformat`` accepts ``...Z`` only in Python 3.11+;
        # normalise to ``+00:00`` defensively.
        normalised = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(normalised)
    except (ValueError, TypeError):
        return None


def _coerce_severity(value: Any) -> int | None:
    # Booleans are an ``int`` subclass — drop them explicitly.
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    if value < _SEVERITY_MIN:
        return _SEVERITY_MIN
    if value > _SEVERITY_MAX:
        return _SEVERITY_MAX
    return value


def _coerce_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _coerce_time_range(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    start_raw = value.get("start")
    end_raw = value.get("end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return None
    start = _parse_iso(start_raw)
    end = _parse_iso(end_raw)
    if start is None or end is None:
        return None
    if start > end:
        return None
    return {"start": start_raw, "end": end_raw}


def parse_response(text: str, *, original_query: str) -> dict[str, object]:
    """Translate the LLM's text response to a filter dict.

    Always returns a dict. On any parse / validation failure falls back to
    ``{"text_query": original_query}`` so the orchestrator can still run a
    keyword query.
    """
    fallback: dict[str, object] = {"text_query": original_query}
    if not text or not text.strip():
        return fallback

    raw_obj = _extract_first_object(text)
    if raw_obj is None:
        return fallback
    try:
        parsed = json.loads(raw_obj)
    except json.JSONDecodeError:
        return fallback
    if not isinstance(parsed, dict):  # pragma: no cover — extractor only emits ``{...}``
        return fallback

    out: dict[str, object] = {}
    severity = _coerce_severity(parsed.get("severity_min")) if "severity_min" in parsed else None
    if severity is not None:
        out["severity_min"] = severity

    for key in _STRING_FIELDS:
        if key in parsed:
            coerced = _coerce_string(parsed[key])
            if coerced is not None:
                out[key] = coerced

    if "time_range_iso" in parsed:
        tr = _coerce_time_range(parsed["time_range_iso"])
        if tr is not None:
            out["time_range_iso"] = tr

    if not out:
        return fallback
    return out
