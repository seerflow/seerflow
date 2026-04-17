"""Text-sanitisation helpers shared across CLI and API surfaces."""

from __future__ import annotations

NOTE_MAX_LENGTH = 512
"""Shared cap for persisted feedback notes. Mirrored by ``FeedbackRequest.note``'s
``Field(max_length=...)``. Keep both in sync via this constant."""

_CONTROL_CODEPOINTS: tuple[int, ...] = (
    *tuple(range(32)),
    0x7F,
    0x85,
    0x2028,
    0x2029,
)
_TRANSLATE_TABLE: dict[int, None] = dict.fromkeys(_CONTROL_CODEPOINTS)


def sanitise_feedback_note(raw: str, *, max_length: int = NOTE_MAX_LENGTH) -> str:
    """Strip C0 controls, DEL, and Unicode line separators from a feedback note.

    Used by both the CLI (``seerflow feedback --note``) and the REST API
    (``FeedbackRequest.note``) so the persisted representation is byte-identical
    regardless of the caller. Uses ``str.translate`` with a precomputed table
    (~20x faster than a generator-expression filter).

    Stripped characters:
      * ``U+0000..U+001F`` (C0 controls, including ``\\n``, ``\\r``, ``\\t``, ``\\x00``).
      * ``U+007F`` (DEL).
      * ``U+0085`` (NEL), ``U+2028`` (LINE SEP), ``U+2029`` (PARAGRAPH SEP) — these
        are newline-equivalent to many log aggregators, JSON parsers, and terminal
        emulators, so permitting them would expose a log-injection vector.

    Other Unicode (Latin-1 accents, CJK, emoji, etc.) is preserved.

    Args:
        raw: Untrusted user input.
        max_length: Upper bound on the returned string length, in Unicode code
            points. Defaults to :data:`NOTE_MAX_LENGTH` (512), matching
            ``FeedbackRequest.note``'s ``Field(max_length=...)``.

    Returns:
        ``raw`` with the stripped characters removed, truncated to at most
        ``max_length`` code points.

    Raises:
        ValueError: If ``max_length`` is negative.
    """
    if max_length < 0:
        raise ValueError("max_length must be non-negative")
    return raw.translate(_TRANSLATE_TABLE)[:max_length]
