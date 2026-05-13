"""Unit tests for ``seerflow templates list|prune|reset`` (S-077, FR-045)."""

from __future__ import annotations

import argparse
import io
import json
from typing import Any
from unittest.mock import patch

import pytest

from seerflow import templates_cmd
from seerflow.cli import parse_args
from seerflow.storage.sqlite import TemplateInfo


def _tinfo(idx: int, count: int = 1) -> TemplateInfo:
    return TemplateInfo(
        template_id=idx,
        template_str=f"Template-{idx} <*>",
        first_seen_ns=1_700_000_000_000_000_000 + idx,
        last_seen_ns=1_700_000_000_000_000_000 + idx * 2,
        event_count=count,
        example_message=f"raw-{idx}",
    )


class _FakeStorage:
    """In-memory storage stub for templates_cmd tests."""

    def __init__(
        self,
        templates: list[TemplateInfo] | None = None,
        *,
        drain_state: bytes | None = None,
    ) -> None:
        self._templates = templates or []
        self._state: dict[str, bytes] = (
            {"drain3:global": drain_state} if drain_state is not None else {}
        )
        self.closed = False
        self.prune_calls: list[int] = []
        self.reset_calls = 0
        self.deleted_state_keys: list[str] = []
        self.load_state_calls: list[str] = []
        self.get_templates_calls: list[int] = []

    async def get_templates(self, limit: int = 1000) -> list[TemplateInfo]:
        self.get_templates_calls.append(limit)
        return sorted(self._templates, key=lambda t: -t.event_count)[:limit]

    async def prune_templates(self, min_count: int) -> int:
        if min_count < 0:
            msg = f"min_count must be >= 0, got {min_count!r}"
            raise ValueError(msg)
        self.prune_calls.append(min_count)
        before = len(self._templates)
        self._templates = [t for t in self._templates if t.event_count >= min_count]
        return before - len(self._templates)

    async def reset_templates(self) -> int:
        self.reset_calls += 1
        removed = len(self._templates)
        self._templates = []
        return removed

    async def load_state(self, key: str) -> bytes | None:
        self.load_state_calls.append(key)
        return self._state.get(key)

    async def delete_state(self, key: str) -> None:
        self.deleted_state_keys.append(key)
        self._state.pop(key, None)

    async def close(self) -> None:
        self.closed = True


def _args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "command": "templates",
        "templates_cmd": "list",
        "limit": 100,
        "json": False,
        "min_count": None,
        "yes": False,
        "config": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# _confirm helper
# ---------------------------------------------------------------------------


class TestConfirm:
    @pytest.mark.unit
    def test_yes_short_circuits(self) -> None:
        stdin = io.StringIO("n\n")
        stdout = io.StringIO()
        assert templates_cmd._confirm("Wipe?", yes=True, stdin=stdin, stdout=stdout) is True
        # Did not consume stdin
        assert stdin.read() == "n\n"
        assert stdout.getvalue() == ""

    @pytest.mark.unit
    def test_yes_input_accepts(self) -> None:
        for answer in ("y", "Y", "yes", "YES", "Yes"):
            stdin = io.StringIO(f"{answer}\n")
            stdout = io.StringIO()
            with patch.object(templates_cmd, "_isatty", return_value=True):
                assert (
                    templates_cmd._confirm("Wipe?", yes=False, stdin=stdin, stdout=stdout) is True
                )

    @pytest.mark.unit
    def test_no_input_rejects(self) -> None:
        for answer in ("n", "N", "no", "", "anything-else"):
            stdin = io.StringIO(f"{answer}\n")
            stdout = io.StringIO()
            with patch.object(templates_cmd, "_isatty", return_value=True):
                assert (
                    templates_cmd._confirm("Wipe?", yes=False, stdin=stdin, stdout=stdout) is False
                )

    @pytest.mark.unit
    def test_non_tty_without_yes_rejects(self) -> None:
        stdin = io.StringIO("y\n")
        stdout = io.StringIO()
        with patch.object(templates_cmd, "_isatty", return_value=False):
            assert templates_cmd._confirm("Wipe?", yes=False, stdin=stdin, stdout=stdout) is False


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_table_output_sorted_desc(self, capsys: pytest.CaptureFixture[str]) -> None:
        storage = _FakeStorage(templates=[_tinfo(1, 5), _tinfo(2, 50), _tinfo(3, 1)])
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            conn.return_value = storage
            rc = await templates_cmd.run_templates(_args(templates_cmd="list"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "TID" in out
        assert "COUNT" in out
        # First data row should be template 2 (count=50)
        body = out.splitlines()
        data_lines = [ln for ln in body if ln.strip() and "TID" not in ln and "---" not in ln]
        # 3 data + summary line
        assert any(line.startswith("2 ") or " 2 " in line for line in data_lines[:3])
        assert storage.closed is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        storage = _FakeStorage()
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            conn.return_value = storage
            rc = await templates_cmd.run_templates(_args(templates_cmd="list"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "No templates found" in out

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        storage = _FakeStorage(templates=[_tinfo(1, 5)])
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            conn.return_value = storage
            rc = await templates_cmd.run_templates(_args(templates_cmd="list", json=True))
        assert rc == 0
        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert isinstance(data, list)
        assert data[0]["template_id"] == 1
        assert data[0]["event_count"] == 5
        assert "first_seen" in data[0]
        assert "last_seen" in data[0]
        assert "template" in data[0]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        storage = _FakeStorage(templates=[_tinfo(i, i) for i in range(1, 5)])
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            conn.return_value = storage
            await templates_cmd.run_templates(_args(templates_cmd="list", limit=2))
        assert storage.get_templates_calls == [2]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_limit_validation_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            rc = await templates_cmd.run_templates(_args(templates_cmd="list", limit=0))
        assert rc == 2
        err = capsys.readouterr().err
        assert "limit" in err.lower()
        conn.assert_not_called()


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


class TestPrune:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_negative_min_count_validation_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            rc = await templates_cmd.run_templates(
                _args(templates_cmd="prune", min_count=-1, yes=True)
            )
        assert rc == 2
        assert "min-count" in capsys.readouterr().err
        conn.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_yes_flag_skips_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        storage = _FakeStorage(templates=[_tinfo(1, 1), _tinfo(2, 5)])
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            conn.return_value = storage
            rc = await templates_cmd.run_templates(
                _args(templates_cmd="prune", min_count=3, yes=True)
            )
        assert rc == 0
        assert storage.prune_calls == [3]
        out = capsys.readouterr().out
        assert "1" in out  # removed=1 reported somewhere
        assert "remaining" in out.lower()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_confirmation_yes_proceeds(self) -> None:
        storage = _FakeStorage(templates=[_tinfo(1, 1)])
        with (
            patch.object(templates_cmd, "_connect_storage_from_args") as conn,
            patch.object(templates_cmd, "_read_confirmation_input", return_value="y"),
            patch.object(templates_cmd, "_isatty", return_value=True),
        ):
            conn.return_value = storage
            rc = await templates_cmd.run_templates(
                _args(templates_cmd="prune", min_count=2, yes=False)
            )
        assert rc == 0
        assert storage.prune_calls == [2]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_confirmation_no_cancels(self, capsys: pytest.CaptureFixture[str]) -> None:
        storage = _FakeStorage(templates=[_tinfo(1, 1)])
        with (
            patch.object(templates_cmd, "_connect_storage_from_args") as conn,
            patch.object(templates_cmd, "_read_confirmation_input", return_value="n"),
            patch.object(templates_cmd, "_isatty", return_value=True),
        ):
            conn.return_value = storage
            rc = await templates_cmd.run_templates(
                _args(templates_cmd="prune", min_count=2, yes=False)
            )
        assert rc == 0
        assert storage.prune_calls == []
        assert "Cancelled" in capsys.readouterr().out

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_tty_without_yes_exits_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        storage = _FakeStorage(templates=[_tinfo(1, 1)])
        with (
            patch.object(templates_cmd, "_connect_storage_from_args") as conn,
            patch.object(templates_cmd, "_isatty", return_value=False),
        ):
            conn.return_value = storage
            rc = await templates_cmd.run_templates(
                _args(templates_cmd="prune", min_count=2, yes=False)
            )
        assert rc == 2
        assert storage.prune_calls == []
        err = capsys.readouterr().err
        assert "--yes" in err

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        storage = _FakeStorage(templates=[_tinfo(1, 1), _tinfo(2, 10)])
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            conn.return_value = storage
            rc = await templates_cmd.run_templates(
                _args(templates_cmd="prune", min_count=5, yes=True, json=True)
            )
        assert rc == 0
        out = capsys.readouterr().out.strip()
        payload = json.loads(out)
        assert payload == {"deleted": 1, "remaining": 1}


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_yes_flag_skips_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        storage = _FakeStorage(
            templates=[_tinfo(1, 1), _tinfo(2, 5)],
            drain_state=b"some-blob",
        )
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            conn.return_value = storage
            rc = await templates_cmd.run_templates(_args(templates_cmd="reset", yes=True))
        assert rc == 0
        assert storage.reset_calls == 1
        assert storage.deleted_state_keys == ["drain3:global"]
        out = capsys.readouterr().out.lower()
        assert "2" in out  # deleted_templates = 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_confirmation_no_cancels(self, capsys: pytest.CaptureFixture[str]) -> None:
        storage = _FakeStorage(templates=[_tinfo(1, 1)])
        with (
            patch.object(templates_cmd, "_connect_storage_from_args") as conn,
            patch.object(templates_cmd, "_read_confirmation_input", return_value="n"),
            patch.object(templates_cmd, "_isatty", return_value=True),
        ):
            conn.return_value = storage
            rc = await templates_cmd.run_templates(_args(templates_cmd="reset", yes=False))
        assert rc == 0
        assert storage.reset_calls == 0
        assert storage.deleted_state_keys == []
        assert "Cancelled" in capsys.readouterr().out

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_json_output_with_drain_state(self, capsys: pytest.CaptureFixture[str]) -> None:
        storage = _FakeStorage(
            templates=[_tinfo(1, 1)],
            drain_state=b"blob",
        )
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            conn.return_value = storage
            rc = await templates_cmd.run_templates(
                _args(templates_cmd="reset", yes=True, json=True)
            )
        assert rc == 0
        out = capsys.readouterr().out.strip()
        payload = json.loads(out)
        assert payload == {"deleted_templates": 1, "drain_state_cleared": True}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_json_output_without_drain_state(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        storage = _FakeStorage(templates=[])
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            conn.return_value = storage
            rc = await templates_cmd.run_templates(
                _args(templates_cmd="reset", yes=True, json=True)
            )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload == {"deleted_templates": 0, "drain_state_cleared": False}


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


class TestParser:
    @pytest.mark.unit
    def test_templates_list(self) -> None:
        args = parse_args(["templates", "list"])
        assert args.command == "templates"
        assert args.templates_cmd == "list"
        assert args.limit == 100
        assert args.json is False

    @pytest.mark.unit
    def test_templates_list_with_limit_and_json(self) -> None:
        args = parse_args(["templates", "list", "--limit", "5", "--json"])
        assert args.limit == 5
        assert args.json is True

    @pytest.mark.unit
    def test_templates_prune_requires_min_count(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["templates", "prune"])

    @pytest.mark.unit
    def test_templates_prune_with_min_count(self) -> None:
        args = parse_args(["templates", "prune", "--min-count", "5", "--yes"])
        assert args.min_count == 5
        assert args.yes is True
        assert args.json is False

    @pytest.mark.unit
    def test_templates_reset(self) -> None:
        args = parse_args(["templates", "reset"])
        assert args.command == "templates"
        assert args.templates_cmd == "reset"
        assert args.yes is False
        assert args.json is False


# ---------------------------------------------------------------------------
# Storage error handling
# ---------------------------------------------------------------------------


class TestStorageErrors:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_runtime_error_propagates_as_exit_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        class _Boom:
            async def get_templates(self, limit: int = 1000) -> list[TemplateInfo]:
                msg = "db on fire"
                raise RuntimeError(msg)

            async def close(self) -> None:
                pass

        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            conn.return_value = _Boom()
            rc = await templates_cmd.run_templates(_args(templates_cmd="list"))
        assert rc == 1
        assert "db on fire" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Dispatcher edge cases
# ---------------------------------------------------------------------------


class TestDispatcher:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unknown_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(templates_cmd, "_connect_storage_from_args") as conn:
            rc = await templates_cmd.run_templates(_args(templates_cmd="WAT"))
        assert rc == 2
        err = capsys.readouterr().err
        assert "unknown templates subcommand" in err
        conn.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reset_non_tty_without_yes_exits_2(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        storage = _FakeStorage(templates=[_tinfo(1, 1)])
        with (
            patch.object(templates_cmd, "_connect_storage_from_args") as conn,
            patch.object(templates_cmd, "_isatty", return_value=False),
        ):
            conn.return_value = storage
            rc = await templates_cmd.run_templates(_args(templates_cmd="reset", yes=False))
        assert rc == 2
        assert storage.reset_calls == 0
        assert "--yes" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# _isatty helper — defensive paths
# ---------------------------------------------------------------------------


class TestIsatty:
    @pytest.mark.unit
    def test_isatty_handles_oserror(self) -> None:
        """Closed stdin (e.g. detached subprocess) raises OSError on isatty()."""

        class _BrokenStdin:
            def isatty(self) -> bool:
                msg = "stdin detached"
                raise OSError(msg)

        with patch.object(templates_cmd.sys, "stdin", _BrokenStdin()):
            assert templates_cmd._isatty() is False

    @pytest.mark.unit
    def test_isatty_handles_attribute_error(self) -> None:
        """An object without an isatty attribute should not crash _isatty."""

        class _NoIsatty:
            pass

        with patch.object(templates_cmd.sys, "stdin", _NoIsatty()):
            assert templates_cmd._isatty() is False
