from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time

import pytest

from seerflow.pipeline.run import (
    _install_shutdown_handlers,
    _noop_capture_signals,
    _ShutdownContext,
)


class _FakePipeline:
    def __init__(self) -> None:
        self.stops = 0

    async def stop(self) -> None:
        self.stops += 1


class _FakeServer:
    """Stand-in exposing only the attribute the shutdown handler touches."""

    def __init__(self) -> None:
        self.should_exit = False


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


@pytest.mark.unit
def test_noop_capture_signals_is_inert() -> None:
    """``_noop_capture_signals`` is a context manager that yields nothing
    and performs no signal-handler installation. Pinning behaviour so a
    future uvicorn upgrade that changes the signal-capture API does not
    silently re-enable uvicorn's handler chain."""
    with _noop_capture_signals() as result:
        assert result is None


@pytest.mark.unit
def test_noop_capture_signals_accepts_self_argument() -> None:
    """If uvicorn ever calls ``self.capture_signals()`` against the patched
    instance, Python passes ``self`` as the first positional arg. The no-op
    must absorb it without ``TypeError`` (covers Py-R #2 finding on PR #209)."""
    sentinel = object()
    with _noop_capture_signals(sentinel):
        pass
    with _noop_capture_signals(sentinel, kw="value"):
        pass


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX signals only")
@pytest.mark.asyncio
async def test_pipeline_stop_exception_is_logged_via_done_callback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing ``pipeline.stop()`` should surface as a WARNING log line
    rather than an unretrieved-task exception at GC. Pins ECC-CR #6 fix."""

    class _FailingPipeline:
        async def stop(self) -> None:
            raise RuntimeError("boom from pipeline.stop")

    pipeline = _FailingPipeline()
    loop = asyncio.get_running_loop()
    ctx = _install_shutdown_handlers(loop, pipeline)
    ctx.server = _FakeServer()

    try:
        with caplog.at_level("WARNING", logger="seerflow"):
            os.kill(os.getpid(), signal.SIGTERM)
            # Give the task time to run + the done_callback to fire.
            for _ in range(20):
                await asyncio.sleep(0.005)
                if ctx.task is not None and ctx.task.done():
                    break

        assert ctx.task is not None
        assert ctx.task.done()
        matches = [r for r in caplog.records if "pipeline.stop() raised" in r.message]
        assert len(matches) == 1, f"expected exactly 1 warning, got {len(matches)}"
    finally:
        _remove_handlers(loop)
