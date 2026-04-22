"""Feedback-event audit-log struct and origin type alias."""

from __future__ import annotations

from typing import Literal

import msgspec

FeedbackOrigin = Literal["dashboard", "cli", "api"]


class FeedbackEvent(msgspec.Struct, frozen=True, gc=False):
    """Append-only audit-log entry for a TP/FP verdict.

    ``id`` is the server-assigned autoincrement row id from the
    ``alert_feedback_events`` table. It is ``0`` for events constructed
    outside the storage layer (e.g., unit-test fixtures); backends set a
    positive, monotonically increasing value on rows read back from the
    database. Frontends use it as a stable React key for history rows.
    """

    alert_id: str
    feedback: Literal["tp", "fp"]
    note: str
    origin: FeedbackOrigin
    submitted_at_ns: int
    id: int = 0
