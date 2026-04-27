from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time

import pytest

from seerflow.pipeline.run import _install_shutdown_handlers, _ShutdownContext


class _FakePipeline:
    def __init__(self) -> None:
        self.stops = 0

    async def stop(self) -> None:
        self.stops += 1


class _FakeServer:
    """Stand-in exposing only the attribute the shutdown handler touches."""

    should_exit = False


def _remove_handlers(loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, ValueError):
            # pragma: no cover -- Windows / not-set
            loop.remove_signal_handler(sig)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_install_returns_context_with_pipeline_and_no_server() -> None:
    pipeline = _FakePipeline()
    loop = asyncio.get_running_loop()

    ctx = _install_shutdown_handlers(loop, pipeline)
    try:
        assert isinstance(ctx, _ShutdownContext)
        assert ctx.pipeline is pipeline
        assert ctx.server is None
        assert ctx.fired is False
        assert ctx.task is None
    finally:
        _remove_handlers(loop)


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX signals only")
@pytest.mark.asyncio
async def test_sigterm_flips_should_exit_within_50ms() -> None:
    pipeline = _FakePipeline()
    loop = asyncio.get_running_loop()
    ctx = _install_shutdown_handlers(loop, pipeline)
    ctx.server = _FakeServer()

    try:
        started = time.monotonic()
        os.kill(os.getpid(), signal.SIGTERM)

        for _ in range(40):
            await asyncio.sleep(0.005)
            if ctx.server.should_exit:
                break
        elapsed_ms = (time.monotonic() - started) * 1000

        assert ctx.server.should_exit is True
        assert elapsed_ms < 50, f"SIGTERM-to-should_exit took {elapsed_ms:.1f} ms"

        await asyncio.sleep(0)
        assert pipeline.stops == 1
    finally:
        _remove_handlers(loop)


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX signals only")
@pytest.mark.asyncio
async def test_repeated_sigterm_is_idempotent() -> None:
    pipeline = _FakePipeline()
    loop = asyncio.get_running_loop()
    ctx = _install_shutdown_handlers(loop, pipeline)
    ctx.server = _FakeServer()

    try:
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.01)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.01)

        assert ctx.server.should_exit is True
        assert pipeline.stops == 1  # not 2
        assert ctx.fired is True
    finally:
        _remove_handlers(loop)


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX signals only")
@pytest.mark.asyncio
async def test_signal_before_server_wired_does_not_crash() -> None:
    """SIGTERM in the gap between handler registration and ``server`` construction
    must still stop the pipeline; ``ctx.server is None`` is tolerated."""
    pipeline = _FakePipeline()
    loop = asyncio.get_running_loop()
    ctx = _install_shutdown_handlers(loop, pipeline)
    # NOTE: ctx.server intentionally left as None.

    try:
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.01)

        assert ctx.fired is True
        assert ctx.server is None
        await asyncio.sleep(0)
        assert pipeline.stops == 1
    finally:
        _remove_handlers(loop)


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX signals only")
@pytest.mark.asyncio
async def test_sigterm_emits_info_log_once(caplog: pytest.LogCaptureFixture) -> None:
    pipeline = _FakePipeline()
    loop = asyncio.get_running_loop()
    ctx = _install_shutdown_handlers(loop, pipeline)
    ctx.server = _FakeServer()

    try:
        with caplog.at_level("INFO", logger="seerflow"):
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(0.01)
            os.kill(os.getpid(), signal.SIGTERM)  # second, gated by `fired`
            await asyncio.sleep(0.01)

        matches = [r for r in caplog.records if "Shutdown signal received" in r.message]
        assert len(matches) == 1, f"expected exactly 1 INFO line, got {len(matches)}"
    finally:
        _remove_handlers(loop)
