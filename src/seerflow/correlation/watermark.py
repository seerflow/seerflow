"""Watermark-based late arrival tolerance for temporal correlation."""

from __future__ import annotations


class Watermark:
    """Tracks event-time progress with configurable late-arrival tolerance.

    Events with ``timestamp_ns < current_ns - tolerance_ns`` are considered
    late and should be excluded from correlation windows.
    """

    __slots__ = ("_current_ns", "_tolerance_ns")

    def __init__(self, tolerance_ns: int) -> None:
        if tolerance_ns < 0:
            msg = f"tolerance_ns must be >= 0, got {tolerance_ns!r}"
            raise ValueError(msg)
        self._tolerance_ns = tolerance_ns
        self._current_ns: int = 0  # 0 means "no advance yet"

    def advance(self, event_time_ns: int) -> None:
        """Advance the watermark if event_time_ns exceeds current position."""
        if event_time_ns > self._current_ns:
            self._current_ns = event_time_ns

    def is_late(self, event_time_ns: int) -> bool:
        """Check if an event is beyond the late-arrival tolerance.

        Returns True if the event is too old to participate in correlation.
        Events within tolerance (or before any advance) return False.
        """
        if self._current_ns == 0:
            return False
        return event_time_ns < self._current_ns - self._tolerance_ns

    @property
    def current_ns(self) -> int:
        """Current watermark position in nanoseconds."""
        return self._current_ns
