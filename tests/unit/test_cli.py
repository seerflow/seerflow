"""Tests for CLI argument parsing and main entry point."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from seerflow.cli import parse_args


class TestCLIArgs:
    def test_version_flag(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["--version"])
        assert exc.value.code == 0

    def test_config_flag(self) -> None:
        args = parse_args(["--config", "/path/to/config.yaml"])
        assert args.config == "/path/to/config.yaml"

    def test_default_no_config(self) -> None:
        args = parse_args([])
        assert args.config is None

    def test_unknown_flag_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["--unknown"])
        assert exc.value.code == 2


class TestMainImport:
    def test_main_callable(self) -> None:
        from seerflow.__main__ import main

        assert callable(main)

    def test_run_callable(self) -> None:
        from seerflow.__main__ import _run

        assert callable(_run)


class TestRunLoop:
    async def test_run_with_no_receivers_stops_cleanly(self) -> None:
        """_run with no receivers and immediate stop."""

        # Run with no config file (defaults, all receivers disabled won't bind)
        # We need a config that disables all receivers to avoid port binding
        from seerflow.config import ReceiverConfig, SeerflowConfig
        from seerflow.pipeline import build_pipeline

        config = SeerflowConfig(
            receivers=ReceiverConfig(
                syslog_enabled=False,
                otlp_grpc_enabled=False,
                otlp_http_enabled=False,
                webhook_enabled=False,
            )
        )
        pipeline = await build_pipeline(config)

        # Inject an event and stop immediately
        from seerflow.receivers.base import RawEvent

        event = RawEvent(
            data=b"test cli event",
            source_type="test",
            source_id="cli-test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await pipeline.manager.put_event(event)

        processed = []

        async def handler(e: RawEvent) -> None:
            processed.append(e)
            await pipeline.stop()

        await pipeline.run(handler)
        assert len(processed) == 1
        assert processed[0].source_type == "test"

    async def test_make_handler_processes_event(self) -> None:
        """_make_handler creates a handler that processes events through ensemble."""
        from seerflow.__main__ import _make_handler
        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        handler = _make_handler(ensemble)

        event = RawEvent(
            data=b"test message",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        # Should not raise
        await handler(event)

    async def test_run_processes_event_and_stops(self, tmp_path: Path) -> None:
        """_run() processes an event and stops cleanly via manager.stop()."""
        from unittest.mock import patch

        from seerflow.__main__ import _run
        from seerflow.receivers.base import RawEvent

        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "receivers:\n"
            "  syslog_enabled: false\n"
            "  otlp_grpc_enabled: false\n"
            "  otlp_http_enabled: false\n"
            "  webhook_enabled: false\n"
        )

        # Patch build_pipeline to get a handle on the pipeline
        built_pipeline = None

        async def _capture_build(config):
            nonlocal built_pipeline
            from seerflow.pipeline import build_pipeline

            built_pipeline = await build_pipeline(config)
            return built_pipeline

        with patch("seerflow.__main__.build_pipeline", side_effect=_capture_build):
            task = asyncio.create_task(_run(str(yaml_file)))
            # Wait for pipeline to be built
            await asyncio.sleep(0.3)
            assert built_pipeline is not None
            # Inject event then stop
            event = RawEvent(
                data=b"cli test event",
                source_type="test",
                source_id="cli",
                received_ns=1_700_000_000_000_000_000,
                metadata={},
            )
            await built_pipeline.manager.put_event(event)
            await asyncio.sleep(0.1)
            await built_pipeline.stop()
            await task  # should complete cleanly

    def test_main_with_nonexistent_config_raises(self) -> None:
        """main() with a bad config path should raise."""
        from seerflow.__main__ import _run
        from seerflow.config import ConfigError

        with pytest.raises(ConfigError, match="not found"):
            asyncio.run(_run("/nonexistent/path.yaml"))

    def test_main_calls_parse_args_and_run(self) -> None:
        """main() wires parse_args → asyncio.run(_run)."""
        import argparse
        from unittest.mock import MagicMock, patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None)
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__.asyncio") as mock_asyncio,
        ):
            mock_asyncio.run = MagicMock()
            main()
            mock_asyncio.run.assert_called_once()

    def test_main_handles_keyboard_interrupt(self) -> None:
        """main() exits cleanly on KeyboardInterrupt."""
        import argparse
        from unittest.mock import MagicMock, patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None)
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__.asyncio") as mock_asyncio,
        ):
            mock_asyncio.run = MagicMock(side_effect=KeyboardInterrupt)
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
