from __future__ import annotations

from seerflow.threat_intel.circuit import AuthCircuitBreaker


def test_starts_closed() -> None:
    cb = AuthCircuitBreaker(threshold=3, open_seconds=60.0, now_fn=lambda: 0.0)
    assert cb.allow() is True
    assert cb.is_open() is False


def test_opens_after_threshold_failures() -> None:
    t = [0.0]
    cb = AuthCircuitBreaker(threshold=3, open_seconds=60.0, now_fn=lambda: t[0])
    for _ in range(3):
        cb.record_failure()
    assert cb.is_open() is True
    assert cb.allow() is False


def test_half_open_after_window() -> None:
    t = [0.0]
    cb = AuthCircuitBreaker(threshold=2, open_seconds=10.0, now_fn=lambda: t[0])
    cb.record_failure()
    cb.record_failure()
    assert cb.allow() is False
    t[0] = 11.0
    assert cb.allow() is True  # half-open probe granted


def test_success_closes_after_half_open() -> None:
    t = [0.0]
    cb = AuthCircuitBreaker(threshold=2, open_seconds=10.0, now_fn=lambda: t[0])
    cb.record_failure()
    cb.record_failure()
    t[0] = 11.0
    cb.allow()  # half-open
    cb.record_success()
    assert cb.is_open() is False
    assert cb.allow() is True


def test_failure_during_half_open_reopens() -> None:
    t = [0.0]
    cb = AuthCircuitBreaker(threshold=2, open_seconds=10.0, now_fn=lambda: t[0])
    cb.record_failure()
    cb.record_failure()
    t[0] = 11.0
    cb.allow()
    cb.record_failure()
    assert cb.is_open() is True
