"""Unit tests for RuleReloader — watchfiles-based hot-reload for correlation rules."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from seerflow.correlation.holders import EngineHolder
from seerflow.correlation.reloader import RuleReloader
from seerflow.correlation.window import EntityWindowBuffer

if TYPE_CHECKING:
    from pathlib import Path

# Valid YAML rule content for writing to temp files.
VALID_RULE_YAML = """\
name: test-rule
entity_type: ip
window_seconds: 600
min_sources: 1
alert_severity: 3
sources:
  - source_type: syslog
    conditions:
      message: "test.*"
    min_count: 1
"""

INVALID_RULE_YAML = """\
name: invalid_rule
entity_type: INVALID_TYPE
window_seconds: -1
"""


class TestRuleReloader:
    """Tests for watchfiles-based rule hot-reload."""

    async def test_reload_correlation_on_file_change(self, tmp_path: Path) -> None:
        """Writing a valid YAML rule file triggers engine reload with new rule."""
        window = EntityWindowBuffer(window_ns=600_000_000_000)
        holder: EngineHolder = EngineHolder(engine=None)
        reloader = RuleReloader(
            correlation_holder=holder,
            correlation_dirs=[str(tmp_path)],
            window_buffer=window,
        )

        task = asyncio.create_task(reloader.watch())
        try:
            # Give the watcher time to start (initial load sees empty dir)
            await asyncio.sleep(0.5)
            assert holder.engine is not None
            assert len(holder.engine._rules) == 0

            # Write a valid rule — watchfiles should detect the change
            (tmp_path / "rule1.yml").write_text(VALID_RULE_YAML)
            await asyncio.sleep(2)

            assert len(holder.engine._rules) == 1
            assert holder.engine._rules[0].name == "test-rule"
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    async def test_invalid_rule_keeps_existing_engine(self, tmp_path: Path) -> None:
        """Invalid rule file is skipped; engine retains previously loaded rules."""
        window = EntityWindowBuffer(window_ns=600_000_000_000)
        holder: EngineHolder = EngineHolder(engine=None)
        reloader = RuleReloader(
            correlation_holder=holder,
            correlation_dirs=[str(tmp_path)],
            window_buffer=window,
        )

        # Pre-seed a valid rule so the initial load produces an engine with 1 rule
        (tmp_path / "good.yml").write_text(VALID_RULE_YAML)

        task = asyncio.create_task(reloader.watch())
        try:
            # Initial load picks up the pre-seeded rule
            await asyncio.sleep(0.5)
            assert holder.engine is not None
            assert len(holder.engine._rules) == 1

            # Write an invalid rule — load_correlation_rules skips it on reload
            (tmp_path / "bad.yml").write_text(INVALID_RULE_YAML)
            await asyncio.sleep(2)

            # Engine should still have exactly the valid rule
            assert holder.engine is not None
            assert len(holder.engine._rules) == 1
            assert holder.engine._rules[0].name == "test-rule"
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    async def test_deleted_rule_removed_from_engine(self, tmp_path: Path) -> None:
        """Deleting a rule file triggers reload with 0 rules."""
        window = EntityWindowBuffer(window_ns=600_000_000_000)
        holder: EngineHolder = EngineHolder(engine=None)
        reloader = RuleReloader(
            correlation_holder=holder,
            correlation_dirs=[str(tmp_path)],
            window_buffer=window,
        )

        # Pre-seed a rule file before starting the watcher
        rule_file = tmp_path / "rule1.yml"
        rule_file.write_text(VALID_RULE_YAML)

        task = asyncio.create_task(reloader.watch())
        try:
            # Initial load picks up the pre-seeded rule
            await asyncio.sleep(0.5)
            assert holder.engine is not None
            assert len(holder.engine._rules) == 1

            # Delete the rule file
            rule_file.unlink()
            await asyncio.sleep(2)

            # Engine should now have 0 rules
            assert holder.engine is not None
            assert len(holder.engine._rules) == 0
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    async def test_watch_returns_immediately_with_no_dirs(self) -> None:
        """watch() returns immediately when no directories are configured."""
        reloader = RuleReloader()
        # Should not block — returns immediately
        await asyncio.wait_for(reloader.watch(), timeout=1.0)

    async def test_reload_uses_asyncio_to_thread(self, tmp_path: Path) -> None:
        """Initial _reload_correlation call is dispatched via asyncio.to_thread."""
        window = EntityWindowBuffer(window_ns=600_000_000_000)
        holder: EngineHolder = EngineHolder(engine=None)
        reloader = RuleReloader(
            correlation_holder=holder,
            correlation_dirs=[str(tmp_path)],
            window_buffer=window,
        )

        to_thread_calls: list[object] = []

        async def fake_to_thread(fn: object, *args: object, **kwargs: object) -> None:
            to_thread_calls.append(fn)
            if callable(fn):
                fn(*args, **kwargs)  # type: ignore[call-arg]

        with patch("seerflow.correlation.reloader.asyncio.to_thread", side_effect=fake_to_thread):
            task = asyncio.create_task(reloader.watch())
            try:
                await asyncio.sleep(0.3)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

        assert len(to_thread_calls) >= 1, "asyncio.to_thread was not called"
        assert to_thread_calls[0] == reloader._reload_correlation

    def test_reload_correlation_warns_when_no_window_buffer(self, tmp_path: Path) -> None:
        """_reload_correlation warns and returns when window_buffer is None."""

        holder: EngineHolder = EngineHolder(engine=None)
        reloader = RuleReloader(
            correlation_holder=holder,
            correlation_dirs=[str(tmp_path)],
            window_buffer=None,
        )
        with patch("seerflow.correlation.reloader._log") as mock_log:
            reloader._reload_correlation()
            mock_log.warning.assert_called_once()
        assert holder.engine is None

    def test_reload_correlation_handles_exception(self, tmp_path: Path) -> None:
        """_reload_correlation logs warning on load failure and keeps existing engine."""

        window = EntityWindowBuffer(window_ns=600_000_000_000)
        holder: EngineHolder = EngineHolder(engine=None)
        reloader = RuleReloader(
            correlation_holder=holder,
            correlation_dirs=[str(tmp_path)],
            window_buffer=window,
        )

        with (
            patch(
                "seerflow.correlation.reloader.load_correlation_rules",
                side_effect=RuntimeError("disk error"),
            ),
            patch("seerflow.correlation.reloader._log") as mock_log,
        ):
            reloader._reload_correlation()
            mock_log.warning.assert_called_once()
        assert holder.engine is None

    # --- S-207 coverage: correlation_holder=None branches ---

    async def test_watch_skips_initial_reload_when_no_holder(
        self, tmp_path: Path
    ) -> None:
        """watch() with ``correlation_holder=None`` skips the initial reload call.

        Covers branch 59→62: the ``if self._correlation_holder is not None`` guard
        takes the falsy path and jumps straight to the watch loop.
        """

        async def _no_changes(*_args: object, **_kwargs: object):
            # Yield nothing, then return — exits the ``async for`` loop immediately.
            if False:
                yield set()

        reloader = RuleReloader(
            correlation_holder=None,
            correlation_dirs=[str(tmp_path)],
            window_buffer=None,
        )

        with (
            patch("seerflow.correlation.reloader.watchfiles.awatch", _no_changes),
            patch("seerflow.correlation.reloader.asyncio.to_thread") as mock_to_thread,
        ):
            await asyncio.wait_for(reloader.watch(), timeout=1.0)

        mock_to_thread.assert_not_called()

    async def test_watch_skips_inner_reload_when_no_holder(
        self, tmp_path: Path
    ) -> None:
        """watch() skips per-change reload when ``correlation_holder`` is None.

        Covers branch 67→62: inside the async-for body, the holder-is-not-None
        check falls through and iterates back to the next change without
        invoking ``_reload_correlation``.
        """

        async def _one_change(*_args: object, **_kwargs: object):
            yield {("modified", str(tmp_path / "rule.yml"))}

        reloader = RuleReloader(
            correlation_holder=None,
            correlation_dirs=[str(tmp_path)],
            window_buffer=None,
        )

        with (
            patch("seerflow.correlation.reloader.watchfiles.awatch", _one_change),
            patch("seerflow.correlation.reloader.asyncio.to_thread") as mock_to_thread,
        ):
            await asyncio.wait_for(reloader.watch(), timeout=1.0)

        mock_to_thread.assert_not_called()

    def test_reload_correlation_skips_engine_swap_when_no_holder(
        self, tmp_path: Path
    ) -> None:
        """_reload_correlation does not assign a new engine when holder is None.

        Covers branch 78→80: the ``if self._correlation_holder is not None``
        guard falls through, leaving no holder to mutate. The subsequent
        "0 rules" warning on line 81 still fires because ``rules`` is empty.
        """
        window = EntityWindowBuffer(window_ns=600_000_000_000)
        reloader = RuleReloader(
            correlation_holder=None,
            correlation_dirs=[str(tmp_path)],
            window_buffer=window,
        )

        with patch("seerflow.correlation.reloader._log") as mock_log:
            reloader._reload_correlation()
            # The 0-rules warning still fires even with no holder to update.
            mock_log.warning.assert_called_once()
