"""Alert webhook dispatcher — async queue + background consumer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WebhookTarget:
    """A configured webhook delivery target."""

    url: str
    format: str  # "slack" | "teams" | "json"
    min_severity: int = 0
