"""Unit test for ``handler.get_normalizer`` accessor (S-081).

The shutdown path in ``pipeline.run`` needs to persist Drain3 templates via
``save_drain_state(parser, store)``. The ``EventNormalizer`` that owns the
``DrainParser`` is constructed inside the ``make_handler`` closure, so the
handler attaches a ``get_normalizer`` lambda mirroring the existing
``get_stats`` accessor (S-080).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.parsing.drain import DrainParser
from seerflow.parsing.normalizer import EventNormalizer
from seerflow.pipeline.handler import make_handler


def _ensemble_mock() -> MagicMock:
    ensemble = MagicMock()
    ensemble.process_event = MagicMock(
        return_value=MagicMock(
            score=0.0,
            is_anomaly=False,
            upper_threshold=1.0,
            anomaly_direction="up",
            source_type="syslog",
        )
    )
    return ensemble


def _storage_mock() -> MagicMock:
    storage = MagicMock()
    storage.write_alert = AsyncMock(return_value=True)
    storage.write_events = AsyncMock()
    storage.write_templates = AsyncMock()
    storage.write_edge = AsyncMock()
    return storage


@pytest.mark.unit
def test_handler_exposes_normalizer_accessor() -> None:
    """``handler.get_normalizer()`` returns the live EventNormalizer."""
    handler = make_handler(
        ensemble=_ensemble_mock(),
        storage=_storage_mock(),
    )
    normalizer = handler.get_normalizer()  # type: ignore[attr-defined]
    assert isinstance(normalizer, EventNormalizer)


@pytest.mark.unit
def test_handler_normalizer_exposes_drain_parser() -> None:
    """Indirection chain handler → normalizer → parser is reachable."""
    handler = make_handler(
        ensemble=_ensemble_mock(),
        storage=_storage_mock(),
    )
    parser = handler.get_normalizer().parser  # type: ignore[attr-defined]
    assert isinstance(parser, DrainParser)


@pytest.mark.unit
def test_handler_normalizer_is_singleton_per_handler() -> None:
    """Two calls return the same instance — the closure owns it."""
    handler = make_handler(
        ensemble=_ensemble_mock(),
        storage=_storage_mock(),
    )
    first = handler.get_normalizer()  # type: ignore[attr-defined]
    second = handler.get_normalizer()  # type: ignore[attr-defined]
    assert first is second
