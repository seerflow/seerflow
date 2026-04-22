"""Unit tests for feedback request/response schema changes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from seerflow.api.schemas import FeedbackEventResponse, FeedbackRequest


def test_feedback_request_origin_defaults_to_api() -> None:
    fb = FeedbackRequest.model_validate({"feedback": "tp"})
    assert fb.origin == "api"


def test_feedback_request_accepts_dashboard_cli() -> None:
    for origin in ("dashboard", "cli", "api"):
        fb = FeedbackRequest.model_validate({"feedback": "tp", "origin": origin})
        assert fb.origin == origin


def test_feedback_request_rejects_unknown_origin() -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest.model_validate({"feedback": "tp", "origin": "gui"})


def test_feedback_event_response_round_trip_json() -> None:
    ev = FeedbackEventResponse(
        id=1,
        feedback="fp",
        note="",
        origin="dashboard",
        submitted_at_ns=1_700_000_000_000_000_000,
    )
    payload = ev.model_dump(mode="json")
    assert payload["submitted_at_ns"] == "1700000000000000000"
    assert payload["id"] == 1
