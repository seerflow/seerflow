"""Tests for the feedback CLI command handler."""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from seerflow.cli import parse_args

_PATCH_LOAD_CONFIG = "seerflow.config.load_config"
_PATCH_CONNECT = "seerflow.feedback_cmd.connect_storage"
_PATCH_ENSEMBLE = "seerflow.detection.ensemble.DetectionEnsemble"
_PATCH_PROCESS = "seerflow.alerting.feedback.process_feedback"


class TestFeedbackCLIParsing:
    """Test that 'seerflow feedback' CLI args parse correctly."""

    def test_feedback_parses_tp(self) -> None:
        args = parse_args(["feedback", "abc-123", "tp"])
        assert args.command == "feedback"
        assert args.alert_id == "abc-123"
        assert args.type == "tp"

    def test_feedback_parses_fp(self) -> None:
        args = parse_args(["feedback", "def-456", "fp"])
        assert args.command == "feedback"
        assert args.alert_id == "def-456"
        assert args.type == "fp"

    def test_feedback_rejects_invalid_type(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["feedback", "abc-123", "invalid"])
        assert exc.value.code == 2

    def test_feedback_note_flag(self) -> None:
        args = parse_args(["feedback", "abc-123", "fp", "--note", "was a test alert"])
        assert args.note == "was a test alert"

    def test_feedback_note_default_empty(self) -> None:
        args = parse_args(["feedback", "abc-123", "tp"])
        assert args.note == ""

    def test_feedback_with_config(self) -> None:
        args = parse_args(["--config", "/etc/seerflow.yaml", "feedback", "id-1", "fp"])
        assert args.config == "/etc/seerflow.yaml"
        assert args.command == "feedback"

    def test_feedback_missing_alert_id_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["feedback"])
        assert exc.value.code == 2

    def test_feedback_missing_type_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["feedback", "abc-123"])
        assert exc.value.code == 2


class TestMainFeedbackDispatch:
    """Test that __main__.py dispatches 'feedback' command."""

    def test_main_dispatches_feedback(self) -> None:
        import asyncio

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(
            config=None,
            command="feedback",
            alert_id="x",
            type="fp",
            note="",
        )

        def _consuming_run_async(coro: object) -> None:
            if asyncio.iscoroutine(coro):
                coro.close()

        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__._run_async") as mock_run_async,
        ):
            mock_run_async.side_effect = _consuming_run_async
            main()
            mock_run_async.assert_called_once()


class TestRunFeedback:
    """Test the run_feedback command handler logic."""

    async def test_run_feedback_success(self) -> None:
        from seerflow.feedback_cmd import run_feedback

        mock_storage = AsyncMock()
        mock_storage.close = AsyncMock()

        mock_ensemble = MagicMock()
        mock_ensemble.load_all_state = AsyncMock(return_value=3)
        mock_ensemble.save_all_state = AsyncMock(return_value=3)

        mock_config = MagicMock()
        mock_config.alerting.pagerduty_routing_key = ""

        args = argparse.Namespace(config=None, alert_id="test-id", type="fp", note="")

        with (
            patch(_PATCH_LOAD_CONFIG, return_value=mock_config),
            patch(
                _PATCH_CONNECT,
                new_callable=AsyncMock,
                return_value=mock_storage,
            ),
            patch(_PATCH_ENSEMBLE, return_value=mock_ensemble),
            patch(
                _PATCH_PROCESS,
                new_callable=AsyncMock,
            ) as mock_pf,
        ):
            mock_pf.return_value = "Alert test-id marked as FP"

            await run_feedback(args)

        mock_pf.assert_awaited_once_with(
            alert_id="test-id",
            feedback="fp",
            storage=mock_storage,
            ensemble=mock_ensemble,
            pagerduty_routing_key="",
            note="",
        )
        mock_ensemble.save_all_state.assert_awaited_once_with(mock_storage)
        mock_storage.close.assert_awaited_once()

    async def test_run_feedback_exits_nonzero_on_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ValueError prints error to stderr and exits with code 1."""
        from seerflow.feedback_cmd import run_feedback

        mock_storage = AsyncMock()
        mock_storage.close = AsyncMock()

        mock_ensemble = MagicMock()
        mock_ensemble.load_all_state = AsyncMock(return_value=0)
        mock_ensemble.save_all_state = AsyncMock(return_value=0)

        mock_config = MagicMock()
        mock_config.alerting.pagerduty_routing_key = ""

        args = argparse.Namespace(config=None, alert_id="bad-id", type="fp", note="")

        with (
            patch(_PATCH_LOAD_CONFIG, return_value=mock_config),
            patch(
                _PATCH_CONNECT,
                new_callable=AsyncMock,
                return_value=mock_storage,
            ),
            patch(_PATCH_ENSEMBLE, return_value=mock_ensemble),
            patch(
                _PATCH_PROCESS,
                new_callable=AsyncMock,
            ) as mock_pf,
            pytest.raises(SystemExit, match="1"),
        ):
            mock_pf.side_effect = ValueError("Alert bad-id not found")
            await run_feedback(args)

        mock_storage.close.assert_awaited_once()
        captured = capsys.readouterr()
        assert "Alert bad-id not found" in captured.err

    async def test_run_feedback_loads_and_saves_ensemble_state(
        self,
    ) -> None:
        """Ensemble state is loaded before and saved after processing."""
        from seerflow.feedback_cmd import run_feedback

        call_order: list[str] = []

        mock_storage = AsyncMock()
        mock_storage.close = AsyncMock()

        mock_ensemble = MagicMock()

        async def mock_load(s: object) -> int:
            call_order.append("load")
            return 2

        async def mock_save(s: object) -> int:
            call_order.append("save")
            return 2

        mock_ensemble.load_all_state = mock_load
        mock_ensemble.save_all_state = mock_save

        mock_config = MagicMock()
        mock_config.alerting.pagerduty_routing_key = ""

        args = argparse.Namespace(config=None, alert_id="id-1", type="tp", note="")

        async def mock_process(**kwargs: object) -> str:
            call_order.append("process")
            return "done"

        with (
            patch(_PATCH_LOAD_CONFIG, return_value=mock_config),
            patch(
                _PATCH_CONNECT,
                new_callable=AsyncMock,
                return_value=mock_storage,
            ),
            patch(_PATCH_ENSEMBLE, return_value=mock_ensemble),
            patch(_PATCH_PROCESS, side_effect=mock_process),
        ):
            await run_feedback(args)

        assert call_order == ["load", "process", "save"]

    async def test_run_feedback_with_note_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """When --note is provided, its length (not content) is logged to avoid PII leak."""
        import logging

        from seerflow.feedback_cmd import run_feedback

        mock_storage = AsyncMock()
        mock_storage.close = AsyncMock()

        mock_ensemble = MagicMock()
        mock_ensemble.load_all_state = AsyncMock(return_value=0)
        mock_ensemble.save_all_state = AsyncMock(return_value=0)

        mock_config = MagicMock()
        mock_config.alerting.pagerduty_routing_key = ""

        args = argparse.Namespace(config=None, alert_id="id-1", type="fp", note="was a test")

        with (
            patch(_PATCH_LOAD_CONFIG, return_value=mock_config),
            patch(
                _PATCH_CONNECT,
                new_callable=AsyncMock,
                return_value=mock_storage,
            ),
            patch(_PATCH_ENSEMBLE, return_value=mock_ensemble),
            patch(
                _PATCH_PROCESS,
                new_callable=AsyncMock,
            ) as mock_pf,
            caplog.at_level(logging.INFO, logger="seerflow"),
        ):
            mock_pf.return_value = "done"
            await run_feedback(args)

        assert any(
            "Persisting feedback note" in r.message and "10 chars" in r.message
            for r in caplog.records
        )
        assert not any("was a test" in r.message for r in caplog.records)

    async def test_run_feedback_uses_storage_factory(self) -> None:
        """run_feedback must dispatch storage selection via connect_storage."""
        from seerflow.feedback_cmd import run_feedback

        mock_storage = AsyncMock()
        mock_storage.close = AsyncMock()

        mock_ensemble = MagicMock()
        mock_ensemble.load_all_state = AsyncMock(return_value=0)
        mock_ensemble.save_all_state = AsyncMock(return_value=0)

        storage_cfg = MagicMock()
        mock_config = MagicMock()
        mock_config.alerting.pagerduty_routing_key = ""
        mock_config.storage = storage_cfg

        args = argparse.Namespace(config=None, alert_id="x", type="fp", note="")

        with (
            patch(_PATCH_LOAD_CONFIG, return_value=mock_config),
            patch(_PATCH_CONNECT, new_callable=AsyncMock, return_value=mock_storage) as mock_conn,
            patch(_PATCH_ENSEMBLE, return_value=mock_ensemble),
            patch(_PATCH_PROCESS, new_callable=AsyncMock) as mock_pf,
        ):
            mock_pf.return_value = "ok"
            await run_feedback(args)

        mock_conn.assert_awaited_once_with(storage_cfg)


class TestFeedbackCmdNote:
    """Tests for --note forwarding through run_feedback into process_feedback."""

    async def test_note_forwarded_to_process_feedback(self) -> None:
        """run_feedback must forward args.note to process_feedback (post-sanitisation)."""
        from seerflow.feedback_cmd import run_feedback

        mock_storage = AsyncMock()
        mock_storage.close = AsyncMock()

        mock_ensemble = MagicMock()
        mock_ensemble.load_all_state = AsyncMock(return_value=0)
        mock_ensemble.save_all_state = AsyncMock(return_value=0)

        mock_config = MagicMock()
        mock_config.alerting.pagerduty_routing_key = ""

        args = argparse.Namespace(
            config=None,
            alert_id="alert-xyz",
            type="fp",
            note="manual review: false positive, known scanner",
        )

        with (
            patch(_PATCH_LOAD_CONFIG, return_value=mock_config),
            patch(
                _PATCH_CONNECT,
                new_callable=AsyncMock,
                return_value=mock_storage,
            ),
            patch(_PATCH_ENSEMBLE, return_value=mock_ensemble),
            patch(
                _PATCH_PROCESS,
                new_callable=AsyncMock,
            ) as mock_pf,
        ):
            mock_pf.return_value = "ok"
            await run_feedback(args)

        kwargs = mock_pf.await_args.kwargs
        assert kwargs.get("note") == "manual review: false positive, known scanner"

    async def test_note_sanitised_before_forwarding(self) -> None:
        """Newlines and CRs are stripped; note is capped at 512 chars."""
        from seerflow.feedback_cmd import run_feedback

        mock_storage = AsyncMock()
        mock_storage.close = AsyncMock()

        mock_ensemble = MagicMock()
        mock_ensemble.load_all_state = AsyncMock(return_value=0)
        mock_ensemble.save_all_state = AsyncMock(return_value=0)

        mock_config = MagicMock()
        mock_config.alerting.pagerduty_routing_key = ""

        raw_note = "line1\nline2\r\nline3" + ("x" * 600)
        args = argparse.Namespace(
            config=None,
            alert_id="alert-xyz",
            type="fp",
            note=raw_note,
        )

        with (
            patch(_PATCH_LOAD_CONFIG, return_value=mock_config),
            patch(
                _PATCH_CONNECT,
                new_callable=AsyncMock,
                return_value=mock_storage,
            ),
            patch(_PATCH_ENSEMBLE, return_value=mock_ensemble),
            patch(
                _PATCH_PROCESS,
                new_callable=AsyncMock,
            ) as mock_pf,
        ):
            mock_pf.return_value = "ok"
            await run_feedback(args)

        kwargs = mock_pf.await_args.kwargs
        forwarded = kwargs.get("note")
        assert isinstance(forwarded, str)
        assert "\n" not in forwarded
        assert "\r" not in forwarded
        assert len(forwarded) == 512
