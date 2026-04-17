"""Tests for seerflow.utils.text.sanitise_feedback_note."""

from __future__ import annotations

import pytest


class TestSanitiseFeedbackNote:
    def test_strips_newline_and_carriage_return(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        assert sanitise_feedback_note("a\nb\rc") == "abc"

    def test_strips_tab(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        assert sanitise_feedback_note("a\tb") == "ab"

    def test_strips_null(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        assert sanitise_feedback_note("a\x00b") == "ab"

    def test_strips_del(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        assert sanitise_feedback_note("a\x7fb") == "ab"

    def test_strips_all_c0_controls(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        raw = "".join(chr(c) for c in range(32)) + "x" + "\x7f"
        assert sanitise_feedback_note(raw) == "x"

    def test_preserves_printable_ascii_and_space(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        assert sanitise_feedback_note("hello world 123!") == "hello world 123!"

    def test_preserves_unicode_above_0x7f(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        assert sanitise_feedback_note("café 日本") == "café 日本"

    def test_truncates_to_max_length(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        assert sanitise_feedback_note("a" * 1000) == "a" * 512

    def test_custom_max_length(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        assert sanitise_feedback_note("a" * 20, max_length=10) == "a" * 10

    def test_strip_happens_before_truncate(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        raw = ("\x00" * 10) + "abcde"
        assert sanitise_feedback_note(raw, max_length=6) == "abcde"

    def test_empty_string_returns_empty(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        assert sanitise_feedback_note("") == ""

    def test_max_length_must_be_non_negative(self) -> None:
        from seerflow.utils.text import sanitise_feedback_note

        with pytest.raises(ValueError, match="max_length must be non-negative"):
            sanitise_feedback_note("abc", max_length=-1)

    def test_strips_unicode_line_separators(self) -> None:
        """U+0085 / U+2028 / U+2029 are newline-equivalent to many log parsers,
        JSON readers, and terminal emulators. They are stripped to close a
        log-injection bypass of the C0 + DEL strip.
        """
        from seerflow.utils.text import sanitise_feedback_note

        assert sanitise_feedback_note("a\u2028b\u2029c\u0085d") == "abcd"

    def test_strips_line_separator_injection_payload(self) -> None:
        """A synthetic log-injection attempt via U+2028 is neutralised."""
        from seerflow.utils.text import sanitise_feedback_note

        payload = "legit note\u2028[SECURITY] admin password changed"
        cleaned = sanitise_feedback_note(payload)
        assert "\u2028" not in cleaned
        assert cleaned == "legit note[SECURITY] admin password changed"

    def test_sanitise_is_idempotent(self) -> None:
        """Applying the sanitiser twice is a no-op — a persisted note round-trips cleanly."""
        from seerflow.utils.text import sanitise_feedback_note

        raw = "hello\nworld\tpayload\x7fend"
        once = sanitise_feedback_note(raw)
        twice = sanitise_feedback_note(once)
        assert once == twice

    def test_exposes_note_max_length_constant(self) -> None:
        """NOTE_MAX_LENGTH is the shared cap — schemas imports it to stay in sync."""
        from seerflow.utils.text import NOTE_MAX_LENGTH, sanitise_feedback_note

        assert NOTE_MAX_LENGTH == 512
        assert sanitise_feedback_note("a" * (NOTE_MAX_LENGTH + 10)) == "a" * NOTE_MAX_LENGTH


class TestCliApiParity:
    """The CLI (sanitise_feedback_note) and API (FeedbackRequest.note) paths
    must produce byte-identical persisted notes for the same raw input."""

    def test_cli_and_api_produce_identical_note(self) -> None:
        from seerflow.api.schemas import FeedbackRequest
        from seerflow.utils.text import sanitise_feedback_note

        # Raw input exercises \n, \r, \t, \x00, \x7f, and a tail of printable chars.
        # Note: Field(max_length=512) would reject a >512-char input at the API
        # before the validator runs, so the parity input is deliberately <=512.
        raw = "hello\nworld\r\n\ttab\x00null\x7fdel end"

        cli_note = sanitise_feedback_note(raw)
        api_note = FeedbackRequest(feedback="fp", note=raw).note

        assert cli_note == "helloworldtabnulldel end"
        assert api_note == cli_note

    def test_cli_and_api_identical_for_mixed_control_input(self) -> None:
        from seerflow.api.schemas import FeedbackRequest
        from seerflow.utils.text import sanitise_feedback_note

        raw = "".join(chr(c) for c in range(32)) + "payload" + "\x7f"

        cli_note = sanitise_feedback_note(raw)
        api_note = FeedbackRequest(feedback="tp", note=raw).note

        assert cli_note == "payload"
        assert api_note == cli_note
