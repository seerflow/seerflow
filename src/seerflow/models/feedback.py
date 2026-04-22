"""Feedback-event audit-log struct and origin type alias."""

from __future__ import annotations

from typing import Literal

import msgspec

FeedbackOrigin = Literal["dashboard", "cli", "api"]


class FeedbackEvent(msgspec.Struct, frozen=True, gc=False):
    """Append-only audit-log entry for a TP/FP verdict."""

    alert_id: str
    feedback: Literal["tp", "fp"]
    note: str
    origin: FeedbackOrigin
    submitted_at_ns: int
