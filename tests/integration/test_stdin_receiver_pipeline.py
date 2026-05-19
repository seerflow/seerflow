"""Integration: stdin pipe -> RawEvent -> pipeline (S-316, FR-082)."""

from __future__ import annotations

import asyncio
import os

from seerflow.config import ReceiverConfig, SeerflowConfig
from seerflow.pipeline import build_pipeline
from seerflow.receivers.manager import ReceiverManager
from seerflow.receivers.stdin import StdinReceiver


async def test_pipe_to_event_to_pipeline() -> None:
    """Write 3 lines into an os.pipe, assert 3 RawEvents reach the manager."""
    mgr = ReceiverManager()
    read_fd, write_fd = os.pipe()
    r = StdinReceiver(
        mgr,
        source_id="stdin",
        line_source=StdinReceiver.pipe_line_source(read_fd),
    )
    await r.start()
    os.write(write_fd, b"line-one\nline-two\nline-three\n")
    os.close(write_fd)  # EOF
    await asyncio.wait_for(r.wait_drained(), timeout=3.0)

    events = [await mgr.get_event() for _ in range(3)]
    datas = [e.data for e in events if e is not None]
    assert datas == [b"line-one", b"line-two", b"line-three"]
    assert all(e is not None and e.source_type == "stdin" for e in events)

    # Clean EOF: receiver stopped, stop() still safe and idempotent.
    assert r.is_healthy() is False
    await r.stop()


async def test_build_pipeline_stdin_only_registers_and_stops() -> None:
    """build_pipeline with stdin_enabled wires the receiver and stops cleanly."""
    cfg = SeerflowConfig(
        receivers=ReceiverConfig(
            stdin_enabled=True,
            syslog_enabled=False,
            otlp_grpc_enabled=False,
            otlp_http_enabled=False,
            webhook_enabled=False,
        )
    )
    pipeline = await build_pipeline(cfg)
    try:
        assert "stdin" in pipeline.manager._receivers
        assert pipeline.manager._receivers["stdin"].is_healthy() is True
    finally:
        await pipeline.stop()
