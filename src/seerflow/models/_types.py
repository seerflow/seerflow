"""Shared type aliases used across models."""

from __future__ import annotations

from typing import Literal

AlertType = Literal["ml", "sigma", "correlation", "ueba", "ioc"]
EntityType = Literal["user", "ip", "host", "process", "file", "domain"]
FeedbackType = Literal["", "tp", "fp"]
