"""Pure prompt builder for the NL hunt translator (S-072, Task 3).

The translator's job is to convert a free-form natural-language threat-hunt
query into a small JSON object that names the structured event filters
``LogStore.query_events`` understands. This module produces a deterministic
prompt string given an NL query — no I/O, no randomness, safe to unit test
in isolation.

The prompt has four sections:

- HEADER: describes the translator task.
- SCHEMA: enumerates the JSON keys the model may emit.
- EXAMPLE: one example NL → JSON pair (anchors the model on the format and
  shows how relative phrases like "last 6 hours" turn into ISO timestamps).
- QUERY + INSTRUCTION: the user's NL query (capped at ``max_query_chars``)
  followed by an instruction to emit ONLY a JSON object.

The user query is bounded before being embedded so a hostile input cannot
blow the prompt budget. Truncation appends a ``...`` marker.
"""

from __future__ import annotations

_TRUNCATE_MARKER = "..."

_HEADER = (
    "TASK:\n"
    "Translate the user's natural language threat-hunt query into a JSON "
    "object describing structured event filters."
)

_SCHEMA = (
    "SCHEMA (any subset of these keys; omit a key when not implied):\n"
    "  time_range_iso: {start: <ISO-8601 UTC>, end: <ISO-8601 UTC>}\n"
    "  source_type:    <string, e.g. 'auth', 'syslog', 'firewall'>\n"
    "  severity_min:   <integer 0..6>\n"
    "  entity_value:   <string, e.g. an IP, username, host>\n"
    "  entity_type:    <string, e.g. 'ip', 'user', 'host'>\n"
    "  text_query:     <free-text keyword search>"
)

_EXAMPLE = (
    "EXAMPLE:\n"
    "  USER QUERY: failed sudo attempts on web-01 in the last 6 hours\n"
    '  JSON: {"time_range_iso": {"start": "2026-01-01T00:00:00Z", '
    '"end": "2026-01-01T06:00:00Z"}, "source_type": "auth", '
    '"entity_value": "web-01", "entity_type": "host", '
    '"text_query": "failed sudo"}'
)

_INSTRUCTION = (
    "INSTRUCTION:\n"
    "Respond with ONLY a JSON object that follows the SCHEMA. "
    "Do not include prose, code fences, or explanations."
)


def _cap_query(value: str, cap: int) -> str:
    if len(value) <= cap:
        return value
    return value[: max(0, cap - len(_TRUNCATE_MARKER))] + _TRUNCATE_MARKER


def build_prompt(nl_query: str, *, max_query_chars: int = 512) -> str:
    """Build a deterministic translation prompt for ``nl_query``.

    Args:
        nl_query: User's natural language hunt query. Must be non-empty
            after whitespace trimming; otherwise ``ValueError`` is raised
            (the orchestrator validates upstream, but the pure builder
            keeps the same contract for safety).
        max_query_chars: Per-field cap for ``nl_query`` before embedding.
            Defaults to 512 characters.

    Returns:
        A multi-section prompt string ready to send to the LLM backend.

    Raises:
        ValueError: if ``nl_query`` is empty or whitespace-only.
    """
    stripped = nl_query.strip()
    if not stripped:
        raise ValueError("nl_query must be non-empty")
    capped = _cap_query(stripped, max_query_chars)
    return f"{_HEADER}\n\n{_SCHEMA}\n\n{_EXAMPLE}\n\nQUERY: {capped}\n\n{_INSTRUCTION}"
