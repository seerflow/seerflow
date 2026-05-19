"""Tests for StdinReceiver — streaming stdin ingestion (S-316, FR-082)."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import TYPE_CHECKING

from seerflow._config_builders import _build_receivers
from seerflow.config import ReceiverConfig, SeerflowConfig
from seerflow.receivers.base import Receiver
from seerflow.receivers.manager import ReceiverManager
from seerflow.receivers.stdin import _MAX_LINE_BYTES, StdinReceiver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import pytest


def _gen(*lines: bytes) -> object:
    """Build a zero-arg factory returning an async iterator over *lines*."""

    async def _iter() -> AsyncIterator[bytes]:
        for ln in lines:
            yield ln

    return lambda: _iter()


class TestConfigWiring:
    def test_receiver_config_has_stdin_enabled_default_false(self) -> None:
        assert ReceiverConfig().stdin_enabled is False

    def test_build_receivers_reads_stdin_enabled(self) -> None:
        assert _build_receivers({"stdin_enabled": True}).stdin_enabled is True

    def test_build_receivers_stdin_enabled_default_false(self) -> None:
        assert _build_receivers({}).stdin_enabled is False


class TestProtocol:
    async def test_isinstance_receiver(self) -> None:
        mgr = ReceiverManager()
        r = StdinReceiver(mgr, source_id="stdin", line_source=_gen())
        assert isinstance(r, Receiver)


class TestLineEmission:
    async def test_lines_become_raw_events(self) -> None:
        mgr = ReceiverManager()
        r = StdinReceiver(mgr, source_id="stdin", line_source=_gen(b"alpha\n", b"beta\n"))
        await r.start()
        await r.wait_drained()
        e1 = await mgr.get_event()
        e2 = await mgr.get_event()
        assert e1 is not None and e2 is not None
        assert e1.data == b"alpha"
        assert e2.data == b"beta"
        assert e1.source_type == "stdin"
        assert e1.source_id == "stdin"
        assert e1.metadata == {}
        assert e1.received_ns > 0

    async def test_trailing_crlf_stripped(self) -> None:
        mgr = ReceiverManager()
        r = StdinReceiver(mgr, source_id="stdin", line_source=_gen(b"win\r\n"))
        await r.start()
        await r.wait_drained()
        e = await mgr.get_event()
        assert e is not None
        assert e.data == b"win"

    async def test_final_line_without_newline_emitted(self) -> None:
        mgr = ReceiverManager()
        r = StdinReceiver(mgr, source_id="stdin", line_source=_gen(b"no-newline"))
        await r.start()
        await r.wait_drained()
        e = await mgr.get_event()
        assert e is not None
        assert e.data == b"no-newline"


class TestFiltering:
    async def test_blank_lines_dropped(self) -> None:
        mgr = ReceiverManager()
        r = StdinReceiver(
            mgr,
            source_id="stdin",
            line_source=_gen(b"\n", b"  \n", b"\t\n", b"real\n"),
        )
        await r.start()
        await r.wait_drained()
        e = await mgr.get_event()
        assert e is not None
        assert e.data == b"real"
        assert mgr.queue_depth == 0

    async def test_oversized_line_discarded(self, caplog: pytest.LogCaptureFixture) -> None:
        mgr = ReceiverManager()
        big = b"x" * (_MAX_LINE_BYTES + 1) + b"\n"
        r = StdinReceiver(mgr, source_id="stdin", line_source=_gen(big, b"ok\n"))
        with caplog.at_level(logging.WARNING):
            await r.start()
            await r.wait_drained()
        e = await mgr.get_event()
        assert e is not None
        assert e.data == b"ok"
        assert mgr.queue_depth == 0
        assert any("oversized" in m.lower() for m in caplog.messages)

    async def test_exactly_max_size_passes(self) -> None:
        mgr = ReceiverManager()
        exact = b"x" * _MAX_LINE_BYTES + b"\n"
        r = StdinReceiver(mgr, source_id="stdin", line_source=_gen(exact))
        await r.start()
        await r.wait_drained()
        e = await mgr.get_event()
        assert e is not None
        assert len(e.data) == _MAX_LINE_BYTES


class TestLifecycle:
    async def test_eof_clean_shutdown(self) -> None:
        mgr = ReceiverManager()
        r = StdinReceiver(mgr, source_id="stdin", line_source=_gen())
        await r.start()
        await r.wait_drained()
        assert r.is_healthy() is False

    async def test_empty_stdin_zero_events(self) -> None:
        mgr = ReceiverManager()
        r = StdinReceiver(mgr, source_id="stdin", line_source=_gen())
        await r.start()
        await r.wait_drained()
        assert mgr.queue_depth == 0

    async def test_stop_idempotent(self) -> None:
        mgr = ReceiverManager()
        r = StdinReceiver(mgr, source_id="stdin", line_source=_gen(b"a\n"))
        await r.start()
        await r.stop()
        await r.stop()
        assert r.is_healthy() is False

    async def test_stop_before_start(self) -> None:
        mgr = ReceiverManager()
        r = StdinReceiver(mgr, source_id="stdin", line_source=_gen())
        await r.stop()
        assert r.is_healthy() is False

    async def test_double_start_noop(self) -> None:
        mgr = ReceiverManager()

        async def _slow() -> AsyncIterator[bytes]:
            await asyncio.sleep(0.05)
            yield b"x\n"

        r = StdinReceiver(mgr, source_id="stdin", line_source=lambda: _slow())
        await r.start()
        first_task = r._read_task
        await r.start()
        assert r._read_task is first_task
        await r.stop()

    async def test_healthy_while_running(self) -> None:
        mgr = ReceiverManager()

        async def _block() -> AsyncIterator[bytes]:
            await asyncio.sleep(1.0)
            yield b"never\n"

        r = StdinReceiver(mgr, source_id="stdin", line_source=lambda: _block())
        await r.start()
        assert r.is_healthy() is True
        await r.stop()
        assert r.is_healthy() is False

    async def test_stop_cancels_running_read(self) -> None:
        mgr = ReceiverManager()

        async def _block() -> AsyncIterator[bytes]:
            await asyncio.sleep(5.0)
            yield b"never\n"

        r = StdinReceiver(mgr, source_id="stdin", line_source=lambda: _block())
        await r.start()
        await asyncio.wait_for(r.stop(), timeout=1.0)
        assert r.is_healthy() is False


class TestRealPipe:
    async def test_default_line_source_reads_real_stdin_fd(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_default_line_source`` resolves ``sys.stdin.fileno()`` + reads it.

        Monkeypatch ``sys.stdin`` with a stand-in whose ``fileno()`` returns a
        real ``os.pipe()`` read end so the production default path (no
        injected ``line_source``) is exercised end-to-end.
        """

        class _FakeStdin:
            def __init__(self, fd: int) -> None:
                self._fd = fd

            def fileno(self) -> int:
                return self._fd

        mgr = ReceiverManager()
        read_fd, write_fd = os.pipe()
        monkeypatch.setattr("seerflow.receivers.stdin.sys.stdin", _FakeStdin(read_fd))
        r = StdinReceiver(mgr, source_id="stdin")  # no line_source -> default
        await r.start()
        os.write(write_fd, b"default-path\n")
        os.close(write_fd)
        await asyncio.wait_for(r.wait_drained(timeout=3.0), timeout=4.0)
        e = await mgr.get_event()
        assert e is not None
        assert e.data == b"default-path"

    async def test_os_pipe_end_to_end(self) -> None:
        mgr = ReceiverManager()
        read_fd, write_fd = os.pipe()
        r = StdinReceiver(
            mgr,
            source_id="stdin",
            line_source=StdinReceiver.pipe_line_source(read_fd),
        )
        await r.start()
        os.write(write_fd, b"piped-line\n")
        os.close(write_fd)
        await asyncio.wait_for(r.wait_drained(), timeout=2.0)
        e = await mgr.get_event()
        assert e is not None
        assert e.data == b"piped-line"
        assert e.source_type == "stdin"
        assert r.is_healthy() is False

    async def test_default_line_source_falls_back_to_executor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mgr = ReceiverManager()
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b"fallback-line\n")
        os.close(write_fd)

        # Force connect_read_pipe to raise so the executor fallback runs.
        async def _boom(*_a: object, **_kw: object) -> None:
            raise OSError("connect_read_pipe rejected")

        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "connect_read_pipe", _boom)

        r = StdinReceiver(
            mgr,
            source_id="stdin",
            line_source=StdinReceiver.pipe_line_source(read_fd),
        )
        await r.start()
        await asyncio.wait_for(r.wait_drained(), timeout=2.0)
        e = await mgr.get_event()
        assert e is not None
        assert e.data == b"fallback-line"

    async def test_stream_reader_drains_limit_overrun(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A >limit line overruns StreamReader; it is drained + discarded.

        Exercises the over-limit ``ValueError`` recovery branch in
        ``_stream_reader_lines`` against a real ``os.pipe()``. The oversized
        line must be dropped with a warning while the following short line
        still arrives intact.

        The full payload is written from a real daemon thread that loops on
        ``os.write`` (pipe writes are partial above the kernel buffer) and
        only then closes the write end, so EOF is guaranteed and the
        event-loop reader drains the giant line concurrently — no deadlock.
        """
        mgr = ReceiverManager()
        read_fd, write_fd = os.pipe()
        payload = b"y" * (_MAX_LINE_BYTES + 4096) + b"\nafter\n"

        def _writer() -> None:
            view = memoryview(payload)
            try:
                while view:
                    n = os.write(write_fd, view)
                    view = view[n:]
            finally:
                os.close(write_fd)

        r = StdinReceiver(
            mgr,
            source_id="stdin",
            line_source=StdinReceiver.pipe_line_source(read_fd),
        )
        with caplog.at_level(logging.WARNING):
            await r.start()
            t = threading.Thread(target=_writer, daemon=True)
            t.start()
            await asyncio.wait_for(r.wait_drained(timeout=8.0), timeout=9.0)
            await asyncio.get_running_loop().run_in_executor(None, t.join, 5.0)
        e = await mgr.get_event()
        assert e is not None
        assert e.data == b"after"
        assert mgr.queue_depth == 0
        assert any("oversized" in m.lower() for m in caplog.messages)


class TestPipelineWiring:
    async def test_build_pipeline_registers_stdin(self) -> None:
        from seerflow.pipeline import build_pipeline

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
        finally:
            await pipeline.stop()

    async def test_build_pipeline_omits_stdin_when_disabled(self) -> None:
        from seerflow.pipeline import build_pipeline

        cfg = SeerflowConfig(
            receivers=ReceiverConfig(
                stdin_enabled=False,
                syslog_enabled=False,
                otlp_grpc_enabled=False,
                otlp_http_enabled=False,
                webhook_enabled=False,
            )
        )
        pipeline = await build_pipeline(cfg)
        try:
            assert "stdin" not in pipeline.manager._receivers
        finally:
            await pipeline.stop()

    def test_exported_from_package(self) -> None:
        from seerflow.receivers import StdinReceiver as Exported

        assert Exported is StdinReceiver
