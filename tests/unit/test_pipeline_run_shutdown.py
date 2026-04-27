from __future__ import annotations

import asyncio

import pytest

from seerflow.pipeline.run import _ShutdownContext, _install_shutdown_handlers


class _FakePipeline:
    def __init__(self) -> None:
        self.stops = 0

    async def stop(self) -> None:
        self.stops += 1


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
        import signal

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, ValueError):
                pass
