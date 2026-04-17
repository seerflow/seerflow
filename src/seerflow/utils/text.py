"""Text-sanitisation helpers shared across CLI and API surfaces."""

from __future__ import annotations

NOTE_MAX_LENGTH = 512
"""Shared cap for persisted feedback notes. Mirrored by ``FeedbackRequest.note``'s
``Field(max_length=...)``. Keep both in sync via this constant."""

_CONTROL_CODEPOINTS: tuple[int, ...] = (*tuple(range(32)), 127)
_TRANSLATE_TABLE: dict[int, None] = dict.fromkeys(_CONTROL_CODEPOINTS)


def sanitise_feedback_note(raw: str, *, max_length: int = NOTE_MAX_LENGTH) -> str:
    """Strip C0 controls and DEL from a user-supplied feedback note, then truncate.

    Used by both the CLI (``seerflow feedback --note``) and the REST API
    (``FeedbackRequest.note``) so the persisted representation is byte-identical
    regardless of the caller. Uses ``str.translate`` with a precomputed table
    (~20x faster than a generator-expression filter).

    Args:
        raw: Untrusted user input.
        max_length: Upper bound on the returned string length, in Unicode code
            points. Defaults to :data:`NOTE_MAX_LENGTH` (512), matching
            ``FeedbackRequest.note``'s ``Field(max_length=...)``.

    Returns:
        ``raw`` with every character in the range ``U+0000..U+001F`` and
        ``U+007F`` (DEL) removed, truncated to at most ``max_length`` code
        points. Characters above ``U+007F`` (including Latin-1 accents, CJK,
        and Unicode line-separator code points such as U+2028 / U+2029) are
        preserved by design; if downstream consumers need to strip them, that
        is a separate concern.

    Raises:
        ValueError: If ``max_length`` is negative.
    """
    if max_length < 0:
        raise ValueError("max_length must be non-negative")
    return raw.translate(_TRANSLATE_TABLE)[:max_length]
