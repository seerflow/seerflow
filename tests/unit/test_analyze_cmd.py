"""Unit tests for ``seerflow analyze`` (S-303, FR-070)."""

from __future__ import annotations

import argparse
import io
import logging
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from seerflow.cli import parse_args

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TextIO

    import pytest


class TestAnalyzeArgparse:
    def test_single_file(self) -> None:
        args = parse_args(["analyze", "/var/log/auth.log"])
        assert args.command == "analyze"
        assert args.paths == ["/var/log/auth.log"]
        assert args.persist is False
        assert args.output is None
        assert args.db is None

    def test_stdin_token(self) -> None:
        args = parse_args(["analyze", "-"])
        assert args.paths == ["-"]

    def test_persist_and_output_and_db(self) -> None:
        args = parse_args(
            ["analyze", "a.log", "b.log", "--persist", "--output", "out.ndjson", "--db", "x.db"]
        )
        assert args.paths == ["a.log", "b.log"]
        assert args.persist is True
        assert args.output == "out.ndjson"
        assert args.db == "x.db"

    def test_no_persist_explicit(self) -> None:
        args = parse_args(["analyze", "a.log", "--no-persist"])
        assert args.persist is False


class TestIterRawEvents:
    def test_yields_events_from_file(self, tmp_path: Path) -> None:
        from seerflow.analyze_cmd import _iter_raw_events

        f = tmp_path / "a.log"
        f.write_text("line one\nline two\n\n")
        events = list(_iter_raw_events([str(f)], stdin=io.StringIO("")))
        assert [e.data for e in events] == [b"line one", b"line two"]
        assert all(e.source_type == "analyze" for e in events)

    def test_reads_stdin_on_dash(self, tmp_path: Path) -> None:
        from seerflow.analyze_cmd import _iter_raw_events

        events = list(_iter_raw_events(["-"], stdin=io.StringIO("piped a\npiped b\n")))
        assert [e.data for e in events] == [b"piped a", b"piped b"]

    def test_skips_binary_file(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        from seerflow.analyze_cmd import _iter_raw_events

        b = tmp_path / "x.bin"
        b.write_bytes(b"ELF\x00\x01" + b"\x00" * 50)
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            events = list(_iter_raw_events([str(b)], stdin=io.StringIO("")))
        assert events == []
        assert "binary" in caplog.text.lower()

    def test_skips_unreadable_file(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        from seerflow.analyze_cmd import _iter_raw_events

        missing = tmp_path / "nope.log"
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            events = list(_iter_raw_events([str(missing)], stdin=io.StringIO("")))
        assert events == []


class TestStorageConfigFor:
    def test_no_persist_is_in_memory(self) -> None:
        from seerflow.analyze_cmd import _storage_config_for
        from seerflow.config import SeerflowConfig

        cfg = _storage_config_for(SeerflowConfig(), persist=False, db=None)
        assert cfg.backend == "sqlite"
        assert cfg.sqlite_path == ":memory:"

    def test_persist_uses_config_storage(self) -> None:
        from seerflow.analyze_cmd import _storage_config_for
        from seerflow.config import SeerflowConfig

        base = SeerflowConfig()
        cfg = _storage_config_for(base, persist=True, db=None)
        assert cfg is base.storage

    def test_persist_db_override(self) -> None:
        from seerflow.analyze_cmd import _storage_config_for
        from seerflow.config import SeerflowConfig

        cfg = _storage_config_for(SeerflowConfig(), persist=True, db="/tmp/x.db")
        assert cfg.sqlite_path == "/tmp/x.db"
        assert cfg.backend == "sqlite"


class TestEmitAlertsNdjson:
    async def test_writes_one_json_object_per_alert(self, tmp_path: Path) -> None:
        import msgspec.json

        from seerflow.analyze_cmd import _emit_alerts_ndjson
        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.storage import connect_storage

        storage = await connect_storage(
            StorageConfig(backend="sqlite", sqlite_path=":memory:", data_dir=str(tmp_path))
        )
        try:
            start_ns = time.time_ns()
            alert = Alert(
                alert_id="00000000-0000-0000-0000-000000000001",
                alert_type="ml",
                timestamp_ns=start_ns + 1000,
                severity_id=SeverityLevel.ERROR,
                rule_name="hst-anomaly",
                description="test",
                entity_uuid="00000000-0000-0000-0000-0000000000aa",
                entity_type="ip",
                entity_value="10.0.0.1",
                contributing_events=(),
            )
            await storage.write_alert(alert, dedup_window_ns=0)
            buf = io.StringIO()
            count = await _emit_alerts_ndjson(storage, buf, start_ns)
            assert count == 1
            obj = msgspec.json.decode(buf.getvalue().strip())
            assert obj["type"] == "ml"
            assert obj["alert_id"] == alert.alert_id
        finally:
            await storage.close()

    async def test_zero_alerts_writes_nothing(self, tmp_path: Path) -> None:
        from seerflow.analyze_cmd import _emit_alerts_ndjson
        from seerflow.config import StorageConfig
        from seerflow.storage import connect_storage

        storage = await connect_storage(
            StorageConfig(backend="sqlite", sqlite_path=":memory:", data_dir=str(tmp_path))
        )
        try:
            buf = io.StringIO()
            count = await _emit_alerts_ndjson(storage, buf, time.time_ns())
            assert count == 0
            assert buf.getvalue() == ""
        finally:
            await storage.close()


def _ns(**kw: object) -> argparse.Namespace:
    base = {"paths": ["x.log"], "output": None, "persist": False, "db": None, "config": None}
    base.update(kw)
    return argparse.Namespace(**base)


class TestRunAnalyze:
    async def test_no_input_returns_2(self, tmp_path: Path) -> None:
        from seerflow.analyze_cmd import run_analyze

        missing = str(tmp_path / "absent.log")
        rc = await run_analyze(_ns(paths=[missing]))
        assert rc == 2

    async def test_zero_alerts_returns_0(self, tmp_path: Path) -> None:
        from seerflow.analyze_cmd import run_analyze

        f = tmp_path / "q.log"
        f.write_text("just one benign line\n")
        out = tmp_path / "out.ndjson"
        rc = await run_analyze(_ns(paths=[str(f)], output=str(out)))
        assert rc == 0
        assert out.read_text() == ""

    async def test_alert_fired_returns_1(self, tmp_path: Path) -> None:
        from seerflow.analyze_cmd import run_analyze

        f = tmp_path / "q.log"
        f.write_text("benign\n")
        out = tmp_path / "out.ndjson"

        async def fake_emit(_storage: object, stream: TextIO, _start: int) -> int:
            stream.write('{"type":"ml"}\n')
            return 1

        with patch("seerflow.analyze_cmd._emit_alerts_ndjson", side_effect=fake_emit):
            rc = await run_analyze(_ns(paths=[str(f)], output=str(out)))
        assert rc == 1
        assert "ml" in out.read_text()

    async def test_bad_output_dir_returns_2(self, tmp_path: Path) -> None:
        from seerflow.analyze_cmd import run_analyze

        f = tmp_path / "q.log"
        f.write_text("x\n")
        rc = await run_analyze(_ns(paths=[str(f)], output="/no/such/dir/out.ndjson"))
        assert rc == 2

    async def test_teardown_runs_on_handler_exception(self, tmp_path: Path) -> None:
        from seerflow.analyze_cmd import run_analyze

        f = tmp_path / "q.log"
        f.write_text("boom\n")
        teardown = AsyncMock()

        class _Assembled:
            handler = AsyncMock(side_effect=RuntimeError("kaboom"))
            lifecycle = ()
            capture_sink = None

            def __init__(self) -> None:
                self.teardown = teardown

        with patch(
            "seerflow.analyze_cmd.assemble_handler",
            new=AsyncMock(return_value=_Assembled()),
        ):
            rc = await run_analyze(_ns(paths=[str(f)]))
        assert rc == 1
        teardown.assert_awaited()


class TestMainDispatch:
    def test_analyze_command_dispatches(self, tmp_path: Path) -> None:
        import sys as _sys

        f = tmp_path / "d.log"
        f.write_text("hi\n")

        called: dict[str, object] = {}

        async def fake_run(args: object) -> int:
            called["paths"] = args.paths  # type: ignore[attr-defined]
            return 0

        argv = ["seerflow", "analyze", str(f)]
        with (
            patch.object(_sys, "argv", argv),
            patch("seerflow.analyze_cmd.run_analyze", side_effect=fake_run),
            patch.object(_sys, "exit") as sys_exit,
        ):
            from seerflow.__main__ import main

            main()
        assert called["paths"] == [str(f)]
        sys_exit.assert_called_once_with(0)
