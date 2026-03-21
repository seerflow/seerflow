"""Shared constants for the parsing pipeline."""

from __future__ import annotations

MAX_MESSAGE_LEN: int = 32_768
MAX_ENTITIES_PER_TYPE: int = 50
MAX_RAW_BYTES: int = MAX_MESSAGE_LEN * 2  # pre-decode byte cap
