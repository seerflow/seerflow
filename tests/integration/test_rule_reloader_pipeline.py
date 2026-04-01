"""Integration tests: rule reloader detects changes and rebuilds engines."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

VALID_RULE_YAML = (
    "name: reload-test\n"
    "entity_type: ip\n"
    "window_seconds: 300\n"
    "min_sources: 1\n"
    "alert_severity: 4\n"
    "sources:\n"
    "  - source_type: syslog\n"
    "    conditions:\n"
    '      message: "reload.*"\n'
    "    min_count: 1\n"
)


class TestReloaderIntegration:
    async def test_reload_logs_success(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Writing a new YAML rule triggers reload and logs success."""
        from seerflow.correlation.holders import EngineHolder
        from seerflow.correlation.reloader import RuleReloader
        from seerflow.correlation.window import EntityWindowBuffer

        rule_dir = tmp_path / "rules"
        rule_dir.mkdir()
        window = EntityWindowBuffer(window_ns=60_000_000_000, max_events=100)
        holder: EngineHolder[object] = EngineHolder(engine=None)

        reloader = RuleReloader(
            correlation_holder=holder,
            correlation_dirs=[str(rule_dir)],
            window_buffer=window,
        )

        task = asyncio.create_task(reloader.watch())
        await asyncio.sleep(0.5)

        with caplog.at_level(logging.INFO, logger="seerflow"):
            (rule_dir / "new.yml").write_text(VALID_RULE_YAML)
            await asyncio.sleep(2.5)

        assert "Reloaded correlation engine with" in caplog.text
        assert holder.engine is not None

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_reload_logs_failure_on_invalid(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Invalid YAML doesn't crash the reloader -- engine still rebuilt with valid rules."""
        from seerflow.correlation.holders import EngineHolder
        from seerflow.correlation.reloader import RuleReloader
        from seerflow.correlation.window import EntityWindowBuffer

        rule_dir = tmp_path / "rules"
        rule_dir.mkdir()
        window = EntityWindowBuffer(window_ns=60_000_000_000, max_events=100)
        holder: EngineHolder[object] = EngineHolder(engine=None)

        reloader = RuleReloader(
            correlation_holder=holder,
            correlation_dirs=[str(rule_dir)],
            window_buffer=window,
        )

        task = asyncio.create_task(reloader.watch())
        await asyncio.sleep(0.5)

        with caplog.at_level(logging.WARNING, logger="seerflow"):
            (rule_dir / "bad.yml").write_text("just a string, not yaml mapping\n")
            await asyncio.sleep(2.5)

        # Reloader should still work (engine rebuilt with 0 valid rules from this dir)
        assert holder.engine is not None
        # Verify warning was logged for the invalid rule
        assert "bad.yml" in caplog.text or "not a valid YAML" in caplog.text

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_no_dirs_watch_returns_immediately(self) -> None:
        """RuleReloader with no dirs returns without blocking."""
        from seerflow.correlation.reloader import RuleReloader

        reloader = RuleReloader()
        await asyncio.wait_for(reloader.watch(), timeout=1.0)
