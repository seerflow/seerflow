"""Shared fixtures for ``pipeline.handler`` coverage tests (S-236).

The handler produced by :func:`seerflow.pipeline.handler.make_handler` fans
the same alert object out to every configured sink (dispatcher / pagerduty /
otlp / ws) and the kill-chain tracker, with an identical ``write_alert`` →
``is_new`` → enqueue → ``except Exception`` shape repeated for UEBA, IoC,
correlation, Sigma, graph-structural, risk-accumulation and ML-anomaly
sources. That setup is copy-pasted across ≥5 tests, so the story's own
guidance ("introduce a thin HandlerTestHarness fixture") applies — this
module centralises it.

Everything here is deterministic: mocks only, no real filesystem, no
network, no sleeps. Time-sensitive gates are driven by the caller patching
``time`` in the module under test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.detection.ensemble import DetectionResult
from seerflow.pipeline.handler import make_handler
from seerflow.receivers.base import RawEvent

# An event message that carries an IP so ``EventNormalizer`` populates
# ``related_ips`` → ``entity_refs`` is non-empty and the entity-gated
# branches (correlation / risk / IoC / graph) become reachable.
_MSG_WITH_ENTITY = b"sshd: failed login from 203.0.113.7 for user alice"


def make_raw_event(
    message: bytes = _MSG_WITH_ENTITY,
    *,
    source_type: str = "syslog",
    source_id: str = "syslog-test",
    received_ns: int = 1_700_000_000_000_000_000,
) -> RawEvent:
    """Build a deterministic :class:`RawEvent` (default carries an IP entity)."""
    return RawEvent(
        data=message,
        source_type=source_type,
        source_id=source_id,
        received_ns=received_ns,
        metadata={},
    )


def make_detection_result(
    *,
    score: float = 0.0,
    is_anomaly: bool = False,
    upper_threshold: float = 1.0,
    lower_threshold: float = 0.0,
    anomaly_direction: str | None = None,
    source_type: str = "syslog",
) -> DetectionResult:
    """Build a real :class:`DetectionResult` (frozen) for the ensemble mock."""
    return DetectionResult(
        score=score,
        upper_threshold=upper_threshold,
        lower_threshold=lower_threshold,
        is_anomaly=is_anomaly,
        anomaly_direction=anomaly_direction,  # type: ignore[arg-type]
        source_type=source_type,
    )


def make_storage(*, write_alert_returns: bool = True) -> MagicMock:
    """AsyncMock-backed storage stub with the methods the handler awaits."""
    storage = MagicMock()
    storage.write_alert = AsyncMock(return_value=write_alert_returns)
    storage.write_events = AsyncMock()
    storage.write_templates = AsyncMock()
    storage.write_edge = AsyncMock()
    return storage


def make_ensemble(result: DetectionResult | None = None) -> MagicMock:
    """Ensemble stub returning a configurable :class:`DetectionResult`."""
    ensemble = MagicMock()
    ensemble.process_event = MagicMock(
        return_value=result if result is not None else make_detection_result()
    )
    ensemble.save_all_state = AsyncMock(return_value=0)
    return ensemble


@dataclass
class HandlerTestHarness:
    """Bundle of mock collaborators + the assembled handler.

    Build the handler with :meth:`build`, passing only the collaborators a
    given test cares about; the rest stay ``None`` (handler treats every
    optional collaborator as feature-flag gated).
    """

    storage: MagicMock = field(default_factory=make_storage)
    ensemble: MagicMock = field(default_factory=make_ensemble)
    dispatcher: MagicMock = field(default_factory=MagicMock)
    pagerduty: MagicMock = field(default_factory=MagicMock)
    otlp: MagicMock = field(default_factory=MagicMock)
    ws_manager: MagicMock = field(default_factory=MagicMock)

    def build(self, **overrides: Any) -> Any:
        """Assemble ``make_handler`` with the bundled mocks + overrides."""
        kwargs: dict[str, Any] = {
            "ensemble": self.ensemble,
            "storage": self.storage,
            "alert_dispatcher": self.dispatcher,
            "pagerduty_sink": self.pagerduty,
            "otlp_sink": self.otlp,
            "ws_manager": self.ws_manager,
        }
        kwargs.update(overrides)
        return make_handler(**kwargs)

    def assert_fanned_out(self, alert: Any) -> None:
        """Assert the alert reached every configured sink exactly via enqueue."""
        self.dispatcher.enqueue.assert_any_call(alert)
        self.pagerduty.enqueue_trigger.assert_any_call(alert)
        self.otlp.enqueue.assert_any_call(alert)
        self.ws_manager.broadcast_alert.assert_any_call(alert)


@pytest.fixture
def harness() -> HandlerTestHarness:
    """Fresh :class:`HandlerTestHarness` per test."""
    return HandlerTestHarness()
