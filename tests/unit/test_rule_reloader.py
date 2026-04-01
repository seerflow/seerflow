"""Unit tests for RuleReloader — watchfiles-based hot-reload for correlation rules."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from seerflow.correlation.holders import EngineHolder
from seerflow.correlation.reloader import RuleReloader
from seerflow.correlation.window import EntityWindowBuffer

if TYPE_CHECKING:
    from pathlib import Path

# Valid YAML rule content for writing to temp files.
VALID_RULE_YAML = """\
name: test_rule
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
            assert holder.engine._rules[0].name == "test_rule"
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
            assert holder.engine._rules[0].name == "test_rule"
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
