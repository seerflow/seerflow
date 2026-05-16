"""Tests for CLI argument parsing and main entry point."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from seerflow.cli import build_parser, parse_args


class TestCLIHelpClarity:
    """S-089: ``--help`` must guide a first-time evaluator (NFR-005/006).

    The ``--config`` flag is optional and zero-config works without it
    (NFR-006); the root help should say so and point at a next step.
    """

    def test_config_help_mentions_optional_and_zero_config(self) -> None:
        """``--config`` help states the flag is optional + zero-config works."""
        parser = build_parser()
        action = parser._option_string_actions["--config"]
        help_text = (action.help or "").lower()
        assert "optional" in help_text
        assert "default" in help_text or "zero-config" in help_text

    def test_parser_description_and_epilog_point_to_docs(self) -> None:
        """Root description is descriptive; epilog points at a command + docs."""
        parser = build_parser()
        description = parser.description or ""
        # Must be more than the old bare one-liner.
        assert len(description) > len("Streaming log intelligence agent")
        epilog = parser.epilog or ""
        assert "seerflow start" in epilog
        assert "operator-guide" in epilog or "README" in epilog


class TestCLIArgs:
    def test_version_flag(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["--version"])
        assert exc.value.code == 0

    def test_config_flag(self) -> None:
        args = parse_args(["--config", "/path/to/config.yaml", "start"])
        assert args.config == "/path/to/config.yaml"

    def test_default_no_config(self) -> None:
        args = parse_args(["start"])
        assert args.config is None

    def test_unknown_flag_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["--unknown"])
        assert exc.value.code == 2


class TestCLIStatusArgs:
    """Parser surface for ``seerflow status`` (S-075)."""

    def test_status_command_default_flags(self) -> None:
        args = parse_args(["status"])
        assert args.command == "status"
        assert args.json is False
        assert args.timeout == 3.0

    def test_status_json_flag(self) -> None:
        args = parse_args(["status", "--json"])
        assert args.command == "status"
        assert args.json is True

    def test_status_custom_timeout(self) -> None:
        args = parse_args(["status", "--timeout", "10"])
        assert args.timeout == 10.0

    def test_status_timeout_too_small_rejected(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["status", "--timeout", "0"])

    def test_status_timeout_too_large_rejected(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["status", "--timeout", "100"])

    def test_status_inherits_config_flag(self) -> None:
        args = parse_args(["--config", "/tmp/c.yaml", "status"])
        assert args.command == "status"
        assert args.config == "/tmp/c.yaml"


class TestCLIStartTUIArgs:
    """Parser surface for ``seerflow start --tui`` (S-079, FR-048)."""

    def test_start_default_tui_false(self) -> None:
        """Without --tui, the start command sets tui=False (backward compat)."""
        args = parse_args(["start"])
        assert args.command == "start"
        assert args.tui is False

    def test_start_tui_flag_enables(self) -> None:
        """--tui sets tui=True so the dispatcher can branch to the TUI path."""
        args = parse_args(["start", "--tui"])
        assert args.command == "start"
        assert args.tui is True

    def test_start_tui_composes_with_global_config(self) -> None:
        """--tui composes with the global --config flag (no parser conflict)."""
        args = parse_args(["--config", "x.yaml", "start", "--tui"])
        assert args.command == "start"
        assert args.tui is True
        assert args.config == "x.yaml"


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
        """make_handler creates a handler that processes events through ensemble."""
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        handler = make_handler(ensemble, mock_storage)

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
        built_event = asyncio.Event()

        async def _capture_build(config):
            nonlocal built_pipeline
            from seerflow.pipeline import build_pipeline

            built_pipeline = await build_pipeline(config)
            built_event.set()
            return built_pipeline

        with patch("seerflow.pipeline.run.build_pipeline", side_effect=_capture_build):
            task = asyncio.create_task(_run(str(yaml_file)))
            # Deterministically wait until the pipeline has been built
            # (replaces a fixed asyncio.sleep(0.3) that flaked under
            # full-suite parallel load — see S-234 / SEE-258).
            await asyncio.wait_for(built_event.wait(), timeout=5.0)
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
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig(
            detection=SeerflowConfig().detection,
        )
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_templates = AsyncMock()
        handler = make_handler(ensemble, mock_storage)

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
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_templates = AsyncMock()
        handler = make_handler(ensemble, mock_storage)

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
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_templates = AsyncMock()
        handler = make_handler(ensemble, mock_storage)

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

    async def test_handler_with_sigma_engine_writes_alerts(self) -> None:
        """When sigma_engine returns alerts, handler writes them to storage."""
        from unittest.mock import AsyncMock, MagicMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models.alert import Alert
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_alert = AsyncMock()

        mock_alert = MagicMock(spec=Alert)
        mock_sigma = MagicMock()
        mock_sigma.evaluate.return_value = [mock_alert]

        from seerflow.correlation.holders import EngineHolder

        handler = make_handler(
            ensemble, mock_storage, sigma_holder=EngineHolder(engine=mock_sigma)
        )

        event = RawEvent(
            data=b"test message",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        mock_sigma.evaluate.assert_called_once()
        mock_storage.write_alert.assert_called()

    async def test_handler_sigma_evaluate_failure_does_not_crash(self) -> None:
        """If sigma_engine.evaluate() raises, the handler logs and continues."""
        from unittest.mock import AsyncMock, MagicMock

        from seerflow.config import SeerflowConfig
        from seerflow.correlation.holders import EngineHolder
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()

        mock_sigma = MagicMock()
        mock_sigma.evaluate.side_effect = RuntimeError("sigma broke")

        handler = make_handler(
            ensemble, mock_storage, sigma_holder=EngineHolder(engine=mock_sigma)
        )

        event = RawEvent(
            data=b"test message",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        # Should not raise despite sigma failure
        await handler(event)

    def test_main_with_nonexistent_config_raises(self) -> None:
        """main() with a bad config path should raise."""
        from seerflow.config import ConfigError
        from seerflow.pipeline.run import _run

        with pytest.raises(ConfigError, match="not found"):
            asyncio.run(_run("/nonexistent/path.yaml"))

    def test_main_calls_parse_args_and_run(self) -> None:
        """main() wires parse_args → asyncio.run(_run) for 'start' command."""
        import argparse
        from unittest.mock import patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None, command="start")
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__._run_async") as mock_run_async,
        ):
            mock_run_async.return_value = None
            main()
            mock_run_async.assert_called_once()

    def test_main_handles_keyboard_interrupt(self) -> None:
        """main() exits cleanly on KeyboardInterrupt."""
        import argparse
        from unittest.mock import patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None, command="start")
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__._run_async") as mock_run_async,
        ):
            mock_run_async.side_effect = KeyboardInterrupt
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0

    async def test_handler_severity_from_metadata(self) -> None:
        """Handler propagates seerflow_severity from RawEvent metadata."""
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models.event import SeverityLevel
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        handler = make_handler(ensemble, mock_storage)

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
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        handler = make_handler(ensemble, mock_storage)

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
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        handler = make_handler(ensemble, mock_storage)

        event = RawEvent(
            data=b"Failed login from 192.168.1.1 by user root on host web01",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        written_event = mock_storage.write_events.call_args[0][0][0]
        import uuid as _uuid

        # entity_refs now contains UUID5 strings, not raw values
        assert len(written_event.entity_refs) > 0
        for ref in written_event.entity_refs:
            parsed = _uuid.UUID(ref)
            assert parsed.version == 5
        # Raw values still in related_* fields
        assert "192.168.1.1" in written_event.related_ips
        # UUID5 strings are different from raw values
        assert written_event.related_ips[0] not in written_event.entity_refs

    async def test_handler_entity_refs_empty_for_plain_message(self) -> None:
        """Handler leaves entity_refs empty when no entities found."""
        from unittest.mock import AsyncMock

        from seerflow.config import SeerflowConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        handler = make_handler(ensemble, mock_storage)

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
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_alert = AsyncMock()
        handler = make_handler(ensemble, mock_storage)

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
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_alert = AsyncMock()
        handler = make_handler(ensemble, mock_storage)

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
        from seerflow.pipeline.handler import make_handler
        from seerflow.receivers.base import RawEvent

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock_storage = AsyncMock()
        mock_storage.write_events = AsyncMock()
        mock_storage.write_alert = AsyncMock(side_effect=Exception("disk full"))
        handler = make_handler(ensemble, mock_storage)

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


class TestStartSubcommand:
    def test_start_subcommand(self) -> None:
        """The 'start' subcommand should parse successfully."""
        args = parse_args(["start"])
        assert args.command == "start"

    def test_start_with_config(self) -> None:
        """The 'start' subcommand accepts --config."""
        args = parse_args(["--config", "/tmp/test.yaml", "start"])
        assert args.command == "start"
        assert args.config == "/tmp/test.yaml"

    def test_no_subcommand_shows_help(self) -> None:
        """Running seerflow with no subcommand should exit with error code 2."""
        with pytest.raises(SystemExit) as exc:
            parse_args([])
        assert exc.value.code == 2


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

    def test_no_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args([])
        assert exc.value.code == 2

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

    def test_main_dispatches_start_tui(self) -> None:
        """main() dispatches `start --tui` to launch_tui_with_pipeline (S-079)."""
        import argparse
        from unittest.mock import patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None, command="start", tui=True)
        sentinel_config = object()
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.config.load_config", return_value=sentinel_config) as mock_load,
            patch("seerflow.tui.launch_tui_with_pipeline") as mock_launch,
            patch("seerflow.__main__._run_async") as mock_run_async,
        ):
            mock_run_async.return_value = None
            main()
            mock_load.assert_called_once_with(None)
            mock_launch.assert_called_once_with(sentinel_config)
            mock_run_async.assert_called_once()

    def test_main_dispatches_start_no_tui(self) -> None:
        """main() dispatches plain `start` to _run, never to the TUI (S-079)."""
        import argparse
        from unittest.mock import patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None, command="start", tui=False)
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.pipeline.run._run") as mock_run,
            patch("seerflow.tui.launch_tui_with_pipeline") as mock_launch,
            patch("seerflow.__main__._run_async") as mock_run_async,
        ):
            mock_run_async.return_value = None
            main()
            mock_run.assert_called_once_with(None)
            mock_launch.assert_not_called()

    def test_main_dispatches_tail(self) -> None:
        """main() dispatches to _build_tail_config + _run_with_config for tail."""
        import argparse
        from unittest.mock import patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None, command="tail", paths=["/tmp/test.log"])
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.pipeline.tail._build_tail_config") as mock_build,
            patch("seerflow.__main__._run_async") as mock_run_async,
        ):
            mock_run_async.return_value = None
            main()
            mock_build.assert_called_once_with(["/tmp/test.log"], config_path=None)
            mock_run_async.assert_called_once()


class TestQueryHealthParsing:
    """S-140: query health subcommand parsing."""

    def test_query_health_parses(self) -> None:
        args = parse_args(["query", "health"])
        assert args.command == "query"
        assert args.query_type == "health"
        assert args.json is False

    def test_query_health_json_flag(self) -> None:
        args = parse_args(["query", "health", "--json"])
        assert args.json is True


class TestGracefulStartupError:
    """S-141: Clean error when all receivers fail to start."""

    async def test_all_receivers_fail_exits_with_code_1(self) -> None:
        from unittest.mock import AsyncMock, patch

        from seerflow.pipeline.run import _run_with_config

        mock_config = AsyncMock()
        mock_config.log_level = "INFO"
        mock_config.storage.data_dir = "/tmp/seerflow-test"
        mock_config.storage.sqlite_path = ":memory:"

        with (
            patch("seerflow.pipeline.run.build_pipeline", new_callable=AsyncMock) as mock_build,
            patch("seerflow.pipeline.run.connect_storage", new_callable=AsyncMock),
            patch("seerflow.llm.build_llm_backend", return_value=None),
            pytest.raises(SystemExit) as exc_info,
        ):
            mock_build.side_effect = RuntimeError("All receivers failed to start: ['syslog']")
            await _run_with_config(mock_config)

        assert exc_info.value.code == 1

    async def test_all_receivers_fail_logs_suggestions(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging
        from unittest.mock import AsyncMock, patch

        from seerflow.pipeline.run import _run_with_config

        mock_config = AsyncMock()
        mock_config.log_level = "INFO"
        mock_config.storage.data_dir = "/tmp/seerflow-test"
        mock_config.storage.sqlite_path = ":memory:"

        with (
            patch("seerflow.pipeline.run.build_pipeline", new_callable=AsyncMock) as mock_build,
            patch("seerflow.pipeline.run.connect_storage", new_callable=AsyncMock),
            patch("seerflow.llm.build_llm_backend", return_value=None),
            caplog.at_level(logging.ERROR, logger="seerflow"),
            pytest.raises(SystemExit),
        ):
            mock_build.side_effect = RuntimeError("All receivers failed to start: ['syslog']")
            await _run_with_config(mock_config)

        assert any("Startup failed" in r.message for r in caplog.records)
        assert any("seerflow.yaml" in r.message for r in caplog.records)

    async def test_partial_failure_logs_warning_and_continues(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When some receivers fail but build_pipeline succeeds, no SystemExit."""
        import logging
        from unittest.mock import AsyncMock, MagicMock, patch

        from seerflow.pipeline import build_pipeline

        mock_mgr = MagicMock()
        mock_mgr._receivers = {"syslog": MagicMock(), "file": MagicMock()}
        mock_mgr.start = AsyncMock(return_value=["file"])  # file failed
        mock_mgr.stop = AsyncMock()
        # syslog is healthy, file is not
        mock_mgr._receivers["syslog"].is_healthy.return_value = True
        mock_mgr._receivers["file"].is_healthy.return_value = False

        mock_config = MagicMock()

        with (
            patch("seerflow.pipeline.ReceiverManager", return_value=mock_mgr),
            caplog.at_level(logging.WARNING),
        ):
            pipeline = await build_pipeline(mock_config)

        assert pipeline is not None
        assert any("Some receivers failed" in r.message for r in caplog.records)


class TestRulesSubcommand:
    def test_parse_rules_list_no_filters(self) -> None:
        from seerflow.cli import parse_args

        ns = parse_args(["rules", "list"])
        assert ns.command == "rules"
        assert ns.rules_cmd == "list"
        assert ns.technique is None
        assert ns.tactic is None
        assert ns.format == "table"

    def test_parse_rules_list_with_all_filters(self) -> None:
        from seerflow.cli import parse_args

        ns = parse_args(
            [
                "rules",
                "list",
                "--technique",
                "T1053",
                "--tactic",
                "persistence",
                "--format",
                "json",
            ]
        )
        assert ns.technique == "T1053"
        assert ns.tactic == "persistence"
        assert ns.format == "json"

    def test_parse_rules_list_rejects_unknown_format(self) -> None:
        from seerflow.cli import parse_args

        with pytest.raises(SystemExit):
            parse_args(["rules", "list", "--format", "yaml"])


class TestCLIExportArgs:
    """Parser surface for ``seerflow export`` (S-076)."""

    def test_parse_export_events_defaults(self) -> None:
        args = parse_args(["export", "events"])
        assert args.command == "export"
        assert args.export_type == "events"
        assert args.format == "json"
        assert args.since == "24h"
        assert args.limit == 100_000
        assert args.output is None
        assert args.source is None
        assert args.severity is None

    def test_parse_export_events_full(self) -> None:
        args = parse_args(
            [
                "export",
                "events",
                "--format",
                "csv",
                "--since",
                "1h",
                "--source",
                "auth",
                "--severity",
                "3",
                "--limit",
                "50",
                "--output",
                "/tmp/out.csv",
            ],
        )
        assert args.export_type == "events"
        assert args.format == "csv"
        assert args.since == "1h"
        assert args.source == "auth"
        assert args.severity == 3
        assert args.limit == 50
        assert args.output == "/tmp/out.csv"

    def test_parse_export_alerts_full(self) -> None:
        args = parse_args(
            [
                "export",
                "alerts",
                "--format",
                "csv",
                "--since",
                "7d",
                "--type",
                "ml",
                "--severity",
                "4",
                "--output",
                "/tmp/x.csv",
            ],
        )
        assert args.export_type == "alerts"
        assert args.format == "csv"
        assert args.type == "ml"
        assert args.severity == 4
        assert args.output == "/tmp/x.csv"

    def test_parse_export_alerts_defaults(self) -> None:
        args = parse_args(["export", "alerts"])
        assert args.export_type == "alerts"
        assert args.format == "json"
        assert args.type is None

    def test_parse_export_rejects_unknown_format(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["export", "events", "--format", "xml"])

    def test_parse_export_requires_export_type(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["export"])


class TestCLIGraphMigrateArgs:
    """Parser surface for ``seerflow graph migrate`` (S-155-F3)."""

    def test_parse_graph_migrate_required_flags(self) -> None:
        args = parse_args(["graph", "migrate", "--from", "igraph", "--to", "falkordb"])
        assert args.command == "graph"
        assert args.graph_cmd == "migrate"
        assert args.from_backend == "igraph"
        assert args.to_backend == "falkordb"
        assert args.batch_size == 5000
        assert args.dry_run is False
        assert args.wipe_destination is False

    def test_parse_graph_migrate_all_flags(self) -> None:
        args = parse_args(
            [
                "graph",
                "migrate",
                "--from",
                "falkordb",
                "--to",
                "postgres_age",
                "--batch-size",
                "100",
                "--dry-run",
                "--wipe-destination",
            ],
        )
        assert args.from_backend == "falkordb"
        assert args.to_backend == "postgres_age"
        assert args.batch_size == 100
        assert args.dry_run is True
        assert args.wipe_destination is True

    def test_parse_graph_migrate_rejects_invalid_from_backend(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["graph", "migrate", "--from", "neo4j", "--to", "igraph"])

    def test_parse_graph_migrate_rejects_invalid_to_backend(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["graph", "migrate", "--from", "igraph", "--to", "neo4j"])

    def test_parse_graph_migrate_requires_from_and_to(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["graph", "migrate"])
        with pytest.raises(SystemExit):
            parse_args(["graph", "migrate", "--from", "igraph"])

    def test_parse_graph_migrate_rejects_zero_batch_size(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(
                ["graph", "migrate", "--from", "igraph", "--to", "falkordb", "--batch-size", "0"],
            )

    def test_parse_graph_migrate_rejects_negative_batch_size(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(
                [
                    "graph",
                    "migrate",
                    "--from",
                    "igraph",
                    "--to",
                    "falkordb",
                    "--batch-size",
                    "-1",
                ],
            )

    def test_parse_graph_requires_subcommand(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["graph"])

    def test_parse_graph_migrate_inherits_config_flag(self) -> None:
        args = parse_args(
            [
                "--config",
                "/tmp/c.yaml",
                "graph",
                "migrate",
                "--from",
                "igraph",
                "--to",
                "falkordb",
            ],
        )
        assert args.config == "/tmp/c.yaml"
        assert args.command == "graph"

    def test_main_dispatches_graph_migrate(self) -> None:
        """main() routes ``graph migrate`` to ``run_graph_migrate`` via _run_async_int."""
        import argparse
        from unittest.mock import patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(
            config=None,
            command="graph",
            graph_cmd="migrate",
            from_backend="igraph",
            to_backend="falkordb",
            batch_size=5000,
            dry_run=False,
            wipe_destination=False,
        )
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__._run_async_int") as mock_runner,
        ):
            mock_runner.return_value = 0
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
            mock_runner.assert_called_once()
