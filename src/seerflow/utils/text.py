"""Text-sanitisation helpers shared across CLI and API surfaces."""

from __future__ import annotations

_CONTROL_CHARS: frozenset[str] = frozenset(chr(c) for c in range(32)) | {"\x7f"}

_DEFAULT_MAX_LENGTH = 512


def sanitise_feedback_note(raw: str, *, max_length: int = _DEFAULT_MAX_LENGTH) -> str:
    """Strip C0 controls and DEL from a user-supplied feedback note, then truncate.

    Used by both the CLI (``seerflow feedback --note``) and the REST API
    (``FeedbackRequest.note``) so the persisted representation is byte-identical
    regardless of the caller.

    Args:
        raw: Untrusted user input.
        max_length: Upper bound on the returned string length, in Unicode code
            points. Defaults to 512, matching ``FeedbackRequest.note``'s
            ``Field(max_length=512)``.

    Returns:
        ``raw`` with every character in the range ``U+0000..U+001F`` and
        ``U+007F`` (DEL) removed, truncated to at most ``max_length`` code
        points. Characters above ``U+007F`` (including Latin-1 accents and
        CJK) are preserved.

    Raises:
        ValueError: If ``max_length`` is negative.
    """
    if max_length < 0:
        raise ValueError("max_length must be non-negative")
    stripped = "".join(ch for ch in raw if ch not in _CONTROL_CHARS)
    return stripped[:max_length]
