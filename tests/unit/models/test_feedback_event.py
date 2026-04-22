"""Unit tests for FeedbackEvent msgspec.Struct."""

from __future__ import annotations

import pytest

from seerflow.models.feedback import FeedbackEvent


def test_feedback_event_is_frozen() -> None:
    ev = FeedbackEvent(
        alert_id="a1",
        feedback="tp",
        note="",
        origin="dashboard",
        submitted_at_ns=1,
    )
    with pytest.raises(AttributeError):
        ev.feedback = "fp"  # type: ignore[misc]


def test_feedback_event_requires_valid_origin() -> None:
    import msgspec
    from msgspec import ValidationError

    payload = {
        "alert_id": "a1",
        "feedback": "tp",
        "note": "",
        "origin": "gui",  # invalid
        "submitted_at_ns": 1,
    }
    with pytest.raises(ValidationError):
        msgspec.convert(payload, type=FeedbackEvent)
