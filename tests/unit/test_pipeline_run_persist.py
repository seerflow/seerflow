"""Unit tests for ``_persist_session_state`` + ``_run_shutdown_sequence`` (S-081).

The cooperative drain layer is split into:

- ``_persist_session_state`` — flush pending templates, persist ML model state,
  flush UEBA baselines, persist Drain3 templates. Best-effort; failures of any
  one step are logged and the others continue.
- ``_run_shutdown_sequence`` — wrap the persist phase in ``asyncio.wait_for``
  with the configured ``shutdown_timeout_s``. On timeout the call returns
  normally so the outer ``finally`` in ``_run_with_config`` can still close
  resources (uvicorn, sinks, storage).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.pipeline.run import (
    _persist_session_state,
    _run_shutdown_sequence,
)


def _make_handler(
    *,
    template_meta_with_pending: bool = False,
    drain_parser: Any | None = None,
) -> Any:
    """Build a duck-typed handler exposing ``get_stats`` + ``get_normalizer``."""
    template_meta: dict[int, Any] = {}
    if template_meta_with_pending:
        meta = MagicMock()
        meta.event_count = 5
        template_meta[1] = meta
    handler = MagicMock()
    handler.get_stats = MagicMock(return_value=(0, 0, template_meta, 1_000.0))
    if drain_parser is None:
        drain_parser = MagicMock()
        drain_parser.get_state = MagicMock(return_value=b"\x01\x02")
        drain_parser.template_count = 0
    normalizer = MagicMock()
    normalizer.parser = drain_parser
    handler.get_normalizer = MagicMock(return_value=normalizer)
    return handler


def _make_storage() -> MagicMock:
    storage = MagicMock()
    storage.write_templates = AsyncMock()
    storage.save_state = AsyncMock()
    return storage


def _make_ensemble(saved: int = 2) -> MagicMock:
    ensemble = MagicMock()
    ensemble.save_all_state = AsyncMock(return_value=saved)
    return ensemble


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_session_state_writes_pending_templates() -> None:
    """Template metadata accumulated by the handler is flushed to storage."""
    handler = _make_handler(template_meta_with_pending=True)
    storage = _make_storage()
    ensemble = _make_ensemble()

    await _persist_session_state(handler, storage, ensemble, baseline_store=None)

    storage.write_templates.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_session_state_saves_model_state() -> None:
    """``ensemble.save_all_state`` is invoked with the storage handle."""
    handler = _make_handler()
    storage = _make_storage()
    ensemble = _make_ensemble(saved=4)

    await _persist_session_state(handler, storage, ensemble, baseline_store=None)

    ensemble.save_all_state.assert_awaited_once_with(storage)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_session_state_saves_drain3_templates() -> None:
    """S-081 NEW: Drain3 template state is persisted via ``save_drain_state``."""
    drain_parser = MagicMock()
    drain_parser.get_state = MagicMock(return_value=b"drain3-blob")
    drain_parser.template_count = 7
    handler = _make_handler(drain_parser=drain_parser)
    storage = _make_storage()
    ensemble = _make_ensemble()

    await _persist_session_state(handler, storage, ensemble, baseline_store=None)

    # ``save_drain_state(parser, store)`` calls ``store.save_state("drain3:global", data)``.
    storage.save_state.assert_awaited_once()
    args = storage.save_state.await_args.args
    assert args[0] == "drain3:global"
    assert args[1] == b"drain3-blob"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_session_state_continues_after_drain3_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Drain3 save failure is logged at WARNING but does not abort the drain."""
    handler = _make_handler()
    storage = _make_storage()
    storage.save_state = AsyncMock(side_effect=RuntimeError("storage offline"))
    ensemble = _make_ensemble()

    with caplog.at_level(logging.WARNING, logger="seerflow"):
        await _persist_session_state(handler, storage, ensemble, baseline_store=None)

    matches = [r for r in caplog.records if "Drain3 state save failed" in r.message]
    assert len(matches) == 1
    # The model save must still have been attempted (best-effort drain).
    ensemble.save_all_state.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_session_state_flushes_ueba_baselines() -> None:
    """When a baseline store is provided, its flush is invoked with storage."""
    handler = _make_handler()
    storage = _make_storage()
    ensemble = _make_ensemble()
    baseline_store = MagicMock()
    baseline_store.flush = AsyncMock()
    baseline_store.__len__ = MagicMock(return_value=3)

    await _persist_session_state(handler, storage, ensemble, baseline_store=baseline_store)

    baseline_store.flush.assert_awaited_once_with(storage)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_session_state_continues_after_model_save_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Model-save failure does not block Drain3 / UEBA persistence."""
    handler = _make_handler()
    storage = _make_storage()
    ensemble = _make_ensemble()
    ensemble.save_all_state = AsyncMock(side_effect=RuntimeError("model boom"))

    with caplog.at_level(logging.WARNING, logger="seerflow"):
        await _persist_session_state(handler, storage, ensemble, baseline_store=None)

    matches = [r for r in caplog.records if "Final model save failed" in r.message]
    assert len(matches) == 1
    # Drain3 persistence still ran despite the model failure.
    storage.save_state.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_shutdown_sequence_emits_start_and_complete_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-081: structured INFO log lines bracket the drain phase."""
    handler = _make_handler()
    storage = _make_storage()
    ensemble = _make_ensemble()

    with caplog.at_level(logging.INFO, logger="seerflow"):
        await _run_shutdown_sequence(
            handler=handler,
            storage=storage,
            ensemble=ensemble,
            baseline_store=None,
            timeout=5.0,
        )

    starts = [r for r in caplog.records if "Seerflow shutdown sequence starting" in r.message]
    completes = [r for r in caplog.records if "Seerflow shutdown sequence completed" in r.message]
    assert len(starts) == 1
    assert len(completes) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_shutdown_sequence_returns_on_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the persist phase exceeds ``timeout`` the helper logs a structured
    warning and returns instead of hanging — caller's ``finally`` block runs
    storage.close() unconditionally."""
    storage = _make_storage()
    ensemble = _make_ensemble()

    async def _slow_save(_store: object) -> int:
        await asyncio.sleep(10)
        return 0

    ensemble.save_all_state = AsyncMock(side_effect=_slow_save)
    handler = _make_handler()

    started = asyncio.get_event_loop().time()
    with caplog.at_level(logging.WARNING, logger="seerflow"):
        await _run_shutdown_sequence(
            handler=handler,
            storage=storage,
            ensemble=ensemble,
            baseline_store=None,
            timeout=0.05,
        )
    elapsed = asyncio.get_event_loop().time() - started

    matches = [r for r in caplog.records if "Shutdown timeout exceeded" in r.message]
    assert len(matches) == 1
    assert elapsed < 1.0, f"timeout helper hung for {elapsed:.2f}s"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_session_state_skips_drain3_when_accessor_missing() -> None:
    """A legacy handler (no ``get_normalizer`` attribute) must not crash the
    drain — Drain3 save is silently skipped."""
    handler = MagicMock(spec=["get_stats"])
    handler.get_stats = MagicMock(return_value=(0, 0, {}, 1_000.0))
    storage = _make_storage()
    ensemble = _make_ensemble()

    await _persist_session_state(handler, storage, ensemble, baseline_store=None)

    storage.save_state.assert_not_awaited()
    ensemble.save_all_state.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_shutdown_sequence_with_no_handler_is_a_noop() -> None:
    """When ``handler is None`` (startup failed before make_handler), the
    sequence still completes; only the resource close phase runs after."""
    storage = _make_storage()
    ensemble = _make_ensemble()

    # Should not raise.
    await _run_shutdown_sequence(
        handler=None,
        storage=storage,
        ensemble=ensemble,
        baseline_store=None,
        timeout=5.0,
    )
