"""S-207: Cover remaining dispatch branches in ``seerflow.__main__.main``.

``test_cli.py`` already covers the ``start``, ``tail``, ``query``, and
``feedback`` branches plus ``KeyboardInterrupt``. This module fills the
remaining gaps: ``import`` (with and without ``--db``), ``rules``, and the
``AssertionError`` fallback for unknown commands.
"""

from __future__ import annotations

import argparse
import inspect
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest


def _close_if_coro(arg: object) -> None:
    """Safely close a coroutine so mocking ``_run_async`` doesn't leak it.

    Without this, patching ``_run_async`` to ``return_value=None`` leaves the
    coroutine argument unawaited, which raises ``RuntimeWarning`` under the
    project's ``-W error`` test policy.
    """
    if inspect.iscoroutine(arg):
        arg.close()


class TestMainDispatchImport:
    """``main()`` dispatches to ``run_import`` for the ``import`` command."""

    def test_import_with_explicit_db(self, tmp_path) -> None:
        """``import`` with ``--db`` set forwards the path and awaits ``run_import``."""
        from seerflow.__main__ import main

        db_path = str(tmp_path / "seerflow.db")
        mock_args = argparse.Namespace(
            config=None,
            command="import",
            paths=["/tmp/events.jsonl"],
            db=db_path,
        )
        mock_run_import = AsyncMock()
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.import_cmd.run_import", mock_run_import),
        ):
            main()

        mock_run_import.assert_awaited_once_with(paths=["/tmp/events.jsonl"], db_path=db_path)

    def test_import_without_db_resolves_from_config_sqlite_path(self, tmp_path) -> None:
        """``import`` with ``--db`` unset falls through to the config's ``sqlite_path``."""
        from seerflow.__main__ import main
        from seerflow.config import SeerflowConfig

        base = SeerflowConfig()
        cfg = replace(
            base, storage=replace(base.storage, sqlite_path=str(tmp_path / "from_cfg.db"))
        )

        mock_args = argparse.Namespace(
            config=None,
            command="import",
            paths=["/tmp/events.jsonl"],
            db=None,
        )
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__._run_async", side_effect=_close_if_coro) as mock_run_async,
            patch("seerflow.config.load_config", return_value=cfg),
        ):
            main()

        mock_run_async.assert_called_once()

    def test_import_without_db_or_sqlite_path_falls_back_to_data_dir(self, tmp_path) -> None:
        """When neither ``--db`` nor ``sqlite_path`` is set, derive from ``data_dir``."""
        from seerflow.__main__ import main
        from seerflow.config import SeerflowConfig

        base = SeerflowConfig()
        cfg = replace(
            base, storage=replace(base.storage, sqlite_path=None, data_dir=str(tmp_path))
        )

        mock_args = argparse.Namespace(
            config=None,
            command="import",
            paths=["/tmp/events.jsonl"],
            db=None,
        )
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__._run_async", side_effect=_close_if_coro) as mock_run_async,
            patch("seerflow.config.load_config", return_value=cfg),
        ):
            main()

        mock_run_async.assert_called_once()


class TestMainDispatchRules:
    """``main()`` dispatches to ``run_rules_list`` for the ``rules`` command."""

    def test_rules_exits_with_run_rules_list_return_code(self) -> None:
        """``rules`` command calls ``sys.exit(run_rules_list(args))``."""
        from seerflow.__main__ import main

        mock_args = argparse.Namespace(
            config=None,
            command="rules",
            rules_cmd="list",
            technique=None,
            tactic=None,
        )
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.rules_cmd.run_rules_list", return_value=0) as mock_run_rules,
            pytest.raises(SystemExit) as exc,
        ):
            main()

        assert exc.value.code == 0
        mock_run_rules.assert_called_once_with(mock_args)

    def test_rules_propagates_non_zero_exit(self) -> None:
        """Non-zero return from ``run_rules_list`` becomes the process exit code."""
        from seerflow.__main__ import main

        mock_args = argparse.Namespace(
            config=None,
            command="rules",
            rules_cmd="list",
            technique=None,
            tactic=None,
        )
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.rules_cmd.run_rules_list", return_value=2),
            pytest.raises(SystemExit) as exc,
        ):
            main()

        assert exc.value.code == 2


class TestMainDispatchFallback:
    """``main()`` raises ``AssertionError`` when the dispatcher sees an unknown command."""

    def test_unknown_command_raises_assertion_error(self) -> None:
        """Safety net for any new command missing from the dispatcher."""
        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None, command="never-added-to-dispatch")
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            pytest.raises(AssertionError, match="never-added-to-dispatch"),
        ):
            main()
