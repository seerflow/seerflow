"""Lenient parser for the LLM's 4-section response (S-071, Task 3).

The model is asked (via the prompt's INSTRUCTION block) to emit:

    SUMMARY: <one line>
    RATIONALE: <one or more lines>
    EVENTS:
    - bullet
    - bullet
    NEXT STEPS:
    - bullet
    - bullet

This parser is forgiving:

- Missing sections → empty string / empty tuple (never an exception).
- ``-`` and ``*`` bullet markers are both accepted.
- Surrounding whitespace and blank lines are stripped.
- If no section header is present at all, the whole text becomes the
  ``summary``.

Pure function; no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SECTION_RE = re.compile(
    r"^(?P<header>SUMMARY|RATIONALE|EVENTS|NEXT STEPS)\s*:\s*(?P<inline>.*)$",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<body>.+?)\s*$")


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedSections:
    """Result of ``parse_response`` — four parsed sections."""

    summary: str
    anomaly_rationale: str
    contributing_events: tuple[str, ...]
    recommended_next_steps: tuple[str, ...]


def _normalise_header(header: str) -> str:
    return header.upper().strip()


def _flush_paragraph(buffer: list[str]) -> str:
    """Collapse a buffer of lines into a single trimmed string."""
    joined = "\n".join(line.strip() for line in buffer).strip()
    return joined


def _extract_bullets(lines: list[str]) -> tuple[str, ...]:
    bullets: list[str] = []
    for line in lines:
        match = _BULLET_RE.match(line)
        if match:
            bullets.append(match.group("body").strip())
    return tuple(bullets)


def parse_response(text: str) -> ParsedSections:
    """Split ``text`` into the four explanation sections.

    The function is forgiving: missing sections produce empty strings or
    empty tuples and never raise.
    """
    if not text or not text.strip():
        return ParsedSections(
            summary="",
            anomaly_rationale="",
            contributing_events=(),
            recommended_next_steps=(),
        )

    sections: dict[str, list[str]] = {
        "SUMMARY": [],
        "RATIONALE": [],
        "EVENTS": [],
        "NEXT STEPS": [],
    }
    current: str | None = None
    saw_any_header = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = _SECTION_RE.match(line.strip())
        if match:
            saw_any_header = True
            current = _normalise_header(match.group("header"))
            inline = match.group("inline").strip()
            if inline:
                sections[current].append(inline)
            continue
        if current is None:
            # Pre-header lines are ignored until we see a header (or fall
            # back to "no headers at all" below).
            continue
        if line:
            sections[current].append(line)

    if not saw_any_header:
        return ParsedSections(
            summary=text.strip(),
            anomaly_rationale="",
            contributing_events=(),
            recommended_next_steps=(),
        )

    summary = _flush_paragraph(sections["SUMMARY"])
    rationale = _flush_paragraph(sections["RATIONALE"])
    events = _extract_bullets(sections["EVENTS"])
    next_steps = _extract_bullets(sections["NEXT STEPS"])

    return ParsedSections(
        summary=summary,
        anomaly_rationale=rationale,
        contributing_events=events,
        recommended_next_steps=next_steps,
    )
