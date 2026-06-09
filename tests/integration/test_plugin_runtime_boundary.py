"""Runtime error-boundary containment for plugin instances (S-370 AC-3).

Proves a plugin that raises at *runtime* is contained behind the existing
per-component error boundaries — logged, never silently swallowed, and never
crashing the pipeline:

* a plugin ``DeliveryTarget`` raising in ``deliver()`` is caught by
  ``NotificationRouter._safe_deliver``;
* a plugin ``Receiver`` raising in ``start()`` is caught by the lifecycle
  helper ``start_plugin_receivers`` and marked ``failed`` without aborting
  siblings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.alerting.router import NotificationRouter
from seerflow.plugins.groups import PluginGroup
from seerflow.plugins.lifecycle import (
    PluginInventory,
    PluginStatus,
    start_plugin_receivers,
)
from seerflow.plugins.records import LoadedPlugins, PluginRecord
from seerflow.plugins.registration import register_plugin_targets
from tests.unit.alert_factory import make_alert

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert


class _ExplodingTarget:
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def min_severity(self) -> int:
        return 0

    async def deliver(self, alert: Alert) -> None:
        msg = "plugin target deliver boom"
        raise RuntimeError(msg)

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None: ...


class _GoodReceiver:
    def __init__(self) -> None:
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None: ...
    def is_healthy(self) -> bool:
        return self.started


class _ExplodingReceiver:
    async def start(self) -> None:
        msg = "plugin receiver start boom"
        raise RuntimeError(msg)

    async def stop(self) -> None: ...
    def is_healthy(self) -> bool:
        return False


@pytest.mark.integration
async def test_plugin_target_runtime_error_is_contained(
    caplog: pytest.LogCaptureFixture,
) -> None:
    router = NotificationRouter(targets=())
    loaded = LoadedPlugins(
        records=(
            PluginRecord(
                group=PluginGroup.DELIVERY_TARGETS,
                name="boom-target",
                distribution="acme",
                version="1.0.0",
                instance=_ExplodingTarget("boom-target"),
            ),
        )
    )
    register_plugin_targets(router, loaded)

    with caplog.at_level("ERROR"):
        # Must NOT raise — the router's _safe_deliver contains it.
        await router._safe_deliver(router._targets["boom-target"], make_alert())

    assert any("boom-target" in r.message for r in caplog.records)


@pytest.mark.integration
async def test_plugin_receiver_start_error_is_contained(
    caplog: pytest.LogCaptureFixture,
) -> None:
    good = _GoodReceiver()
    loaded = LoadedPlugins(
        records=(
            PluginRecord(
                group=PluginGroup.RECEIVERS,
                name="boom-receiver",
                distribution="acme",
                version="1.0.0",
                instance=_ExplodingReceiver(),
            ),
            PluginRecord(
                group=PluginGroup.RECEIVERS,
                name="good-receiver",
                distribution="acme",
                version="1.0.0",
                instance=good,
            ),
        )
    )
    inventory = PluginInventory(loaded)

    with caplog.at_level("WARNING"):
        # Must NOT raise — lifecycle helper isolates the failure.
        await start_plugin_receivers(inventory)

    assert good.started  # sibling unaffected
    status = {row.id: row.status for row in inventory.entries()}
    assert status["seerflow.receivers:boom-receiver"] is PluginStatus.FAILED
    assert status["seerflow.receivers:good-receiver"] is PluginStatus.STARTED
    assert any("boom-receiver" in r.message for r in caplog.records)
