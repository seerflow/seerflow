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
        from seerflow.pipeline.run import _run

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
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        handler = _make_handler(ensemble, mock_storage)

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

        from seerflow.pipeline.run import _run
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

        with patch("seerflow.pipeline.run.build_pipeline", side_effect=_capture_build):
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

    async def test_handler_per_event_write_and_stats(self) -> None:
        """Handler writes each event individually (WriteBuffer handles batching)."""
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig(
            detection=SeerflowConfig().detection,
        )
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_templates = AsyncMock()
        handler = _make_handler(ensemble, mock_storage)

        # Send 55 events — each should call write_events individually
        for i in range(55):
            event = RawEvent(
                data=f"event {i}".encode(),
                source_type="test",
                source_id="t",
                received_ns=1_700_000_000_000_000_000 + i,
                metadata={},
            )
            await handler(event)

        # write_events called once per event (WriteBuffer handles batching)
        assert mock_storage.write_events.call_count == 55

        # Stats should be accessible
        get_stats = handler.get_stats  # type: ignore[union-attr]
        events, anomalies, templates, t0 = get_stats()
        assert events == 55
        assert anomalies >= 0
        assert len(templates) >= 1
        assert t0 > 0

    async def test_handler_tracks_template_metadata(self) -> None:
        """Handler flushes template metadata alongside events."""
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_templates = AsyncMock()
        handler = _make_handler(ensemble, mock_storage)

        # Send 55 events — template flush triggers at event_count % 10 == 0
        for i in range(55):
            event = RawEvent(
                data=f"event {i}".encode(),
                source_type="test",
                source_id="t",
                received_ns=1_700_000_000_000_000_000 + i,
                metadata={},
            )
            await handler(event)

        # write_templates called at events 10, 20, 30, 40, 50
        assert mock_storage.write_templates.call_count == 5
        templates_arg = mock_storage.write_templates.call_args[0][0]
        assert len(templates_arg) >= 1  # at least 1 template discovered
        # Each template should be a TemplateInfo
        from seerflow.storage.sqlite import TemplateInfo

        for t in templates_arg:
            assert isinstance(t, TemplateInfo)
            assert t.template_id >= 0  # no -1 templates
            assert t.event_count >= 1

    async def test_handler_logs_new_template_discovery(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Handler logs INFO when a new template is discovered."""
        import logging
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_templates = AsyncMock()
        handler = _make_handler(ensemble, mock_storage)

        with caplog.at_level(logging.INFO, logger="seerflow"):
            event = RawEvent(
                data=b"Failed login from 10.0.1.5",
                source_type="test",
                source_id="t",
                received_ns=1_700_000_000_000_000_000,
                metadata={},
            )
            await handler(event)

        new_template_logs = [r for r in caplog.records if "New template discovered" in r.message]
        assert len(new_template_logs) >= 1

    def test_main_with_nonexistent_config_raises(self) -> None:
        """main() with a bad config path should raise."""
        from seerflow.config import ConfigError
        from seerflow.pipeline.run import _run

        with pytest.raises(ConfigError, match="not found"):
            asyncio.run(_run("/nonexistent/path.yaml"))

    def test_main_calls_parse_args_and_run(self) -> None:
        """main() wires parse_args → asyncio.run(_run)."""
        import argparse
        from unittest.mock import MagicMock, patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None, command=None)
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

        mock_args = argparse.Namespace(config=None, command=None)
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__.asyncio") as mock_asyncio,
        ):
            mock_asyncio.run = MagicMock(side_effect=KeyboardInterrupt)
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0

    async def test_handler_severity_from_metadata(self) -> None:
        """Handler propagates seerflow_severity from RawEvent metadata."""
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models.event import SeverityLevel
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        handler = _make_handler(ensemble, mock_storage)

        event = RawEvent(
            data=b"kernel panic - not syncing",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={"seerflow_severity": 4},  # ERROR
        )
        await handler(event)

        written_event = mock_storage.write_events.call_args[0][0][0]
        assert written_event.severity_id == SeverityLevel.ERROR

    async def test_handler_severity_default_no_metadata(self) -> None:
        """Handler defaults to INFORMATIONAL when no seerflow_severity in metadata."""
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models.event import SeverityLevel
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        handler = _make_handler(ensemble, mock_storage)

        event = RawEvent(
            data=b"normal log line",
            source_type="file",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        written_event = mock_storage.write_events.call_args[0][0][0]
        assert written_event.severity_id == SeverityLevel.INFORMATIONAL

    async def test_handler_entity_refs_derived_from_typed_fields(self) -> None:
        """Handler populates entity_refs from related_ips + related_users + related_hosts."""
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        handler = _make_handler(ensemble, mock_storage)

        event = RawEvent(
            data=b"Failed login from 192.168.1.1 by user root on host web01",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        written_event = mock_storage.write_events.call_args[0][0][0]
        # entity_refs should be the concatenation of typed fields
        assert written_event.entity_refs == (
            written_event.related_ips + written_event.related_users + written_event.related_hosts
        )
        # At least IPs should be extracted
        assert "192.168.1.1" in written_event.related_ips
        assert len(written_event.entity_refs) > 0

    async def test_handler_entity_refs_empty_for_plain_message(self) -> None:
        """Handler leaves entity_refs empty when no entities found."""
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        handler = _make_handler(ensemble, mock_storage)

        event = RawEvent(
            data=b"simple log message with no entities",
            source_type="file",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        written_event = mock_storage.write_events.call_args[0][0][0]
        assert written_event.entity_refs == ()
        assert written_event.related_ips == ()
        assert written_event.related_users == ()
        assert written_event.related_hosts == ()

    async def test_handler_writes_alert_on_anomaly(self) -> None:
        """Handler calls write_alert when ensemble detects anomaly."""
        from unittest.mock import AsyncMock, patch

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble, DetectionResult
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_alert = AsyncMock()
        handler = _make_handler(ensemble, mock_storage)

        anomaly_result = DetectionResult(
            score=0.95,
            upper_threshold=0.70,
            lower_threshold=0.10,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="syslog",
        )
        with patch.object(type(ensemble), "process_event", return_value=anomaly_result):
            event = RawEvent(
                data=b"kernel panic - not syncing",
                source_type="syslog",
                source_id="test",
                received_ns=1_700_000_000_000_000_000,
                metadata={"seerflow_severity": 5},
            )
            await handler(event)

        mock_storage.write_alert.assert_called_once()
        alert = mock_storage.write_alert.call_args[0][0]
        assert alert.alert_type == "ml"
        assert alert.risk_score == 0.95
        assert alert.dedup_key.startswith("hst:")
        assert alert.rule_name == "hst-anomaly"

    async def test_handler_no_alert_on_normal_event(self) -> None:
        """Handler does NOT call write_alert when no anomaly detected."""
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_alert = AsyncMock()
        handler = _make_handler(ensemble, mock_storage)

        event = RawEvent(
            data=b"normal log message",
            source_type="file",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        mock_storage.write_alert.assert_not_called()

    async def test_handler_alert_write_failure_does_not_crash(self) -> None:
        """write_alert failure is caught and logged, pipeline continues."""
        from unittest.mock import AsyncMock, patch

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble, DetectionResult
        from seerflow.pipeline.handler import _make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_alert = AsyncMock(side_effect=Exception("disk full"))
        handler = _make_handler(ensemble, mock_storage)

        anomaly_result = DetectionResult(
            score=0.95,
            upper_threshold=0.70,
            lower_threshold=0.10,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="syslog",
        )
        with patch.object(type(ensemble), "process_event", return_value=anomaly_result):
            event = RawEvent(
                data=b"test anomaly",
                source_type="syslog",
                source_id="test",
                received_ns=1_700_000_000_000_000_000,
                metadata={},
            )
            await handler(event)  # Should not raise


class TestTailSubcommand:
    def test_tail_parses_single_path(self) -> None:
        args = parse_args(["tail", "/var/log/syslog"])
        assert args.command == "tail"
        assert args.paths == ["/var/log/syslog"]

    def test_tail_parses_multiple_paths(self) -> None:
        args = parse_args(["tail", "/var/log/syslog", "/var/log/auth.log"])
        assert args.paths == ["/var/log/syslog", "/var/log/auth.log"]

    def test_tail_with_config_before_subcommand(self) -> None:
        args = parse_args(["--config", "my.yaml", "tail", "/var/log/syslog"])
        assert args.paths == ["/var/log/syslog"]
        assert args.config == "my.yaml"

    def test_default_command_is_none(self) -> None:
        args = parse_args([])
        assert args.command is None

    def test_tail_no_paths_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["tail"])
        assert exc.value.code == 2

    def test_build_tail_config_no_base(self) -> None:
        """_build_tail_config with no config_path uses defaults."""
        from seerflow.pipeline.tail import _build_tail_config

        config = _build_tail_config(["/tmp/test.log", "/tmp/other.log"])
        assert config.receivers.file_paths == ("/tmp/test.log", "/tmp/other.log")
        assert config.receivers.syslog_enabled is False
        assert config.receivers.otlp_grpc_enabled is False
        assert config.receivers.otlp_http_enabled is False
        assert config.receivers.webhook_enabled is False

    def test_build_tail_config_with_base(self, tmp_path: Path) -> None:
        """_build_tail_config with config_path inherits detection/storage."""
        from seerflow.pipeline.tail import _build_tail_config

        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("log_level: DEBUG\ndetection:\n  hst_window_size: 500\n")
        config = _build_tail_config(["/tmp/x.log"], config_path=str(yaml_file))
        assert config.receivers.file_paths == ("/tmp/x.log",)
        assert config.receivers.syslog_enabled is False
        assert config.log_level == "DEBUG"
        assert config.detection.hst_window_size == 500

    def test_main_dispatches_tail(self) -> None:
        """main() dispatches to _build_tail_config + _run_with_config for tail."""
        import argparse
        from unittest.mock import MagicMock, patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None, command="tail", paths=["/tmp/test.log"])
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.pipeline.tail._build_tail_config") as mock_build,
            patch("seerflow.__main__.asyncio") as mock_asyncio,
        ):
            mock_asyncio.run = MagicMock()
            main()
            mock_build.assert_called_once_with(["/tmp/test.log"], config_path=None)
            mock_asyncio.run.assert_called_once()
