"""Unit tests for the pipeline plugin-wiring helper (S-370 Task 6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from seerflow.config import PluginsConfig
from seerflow.plugins.groups import PluginGroup
from seerflow.plugins.lifecycle import PluginStatus
from seerflow.plugins.pipeline_wiring import load_and_wire_plugins, stop_plugin_lifecycle
from seerflow.receivers.manager import ReceiverManager

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert


class _GoodReceiver:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def is_healthy(self) -> bool:
        return self.started and not self.stopped


class _GoodTarget:
    @property
    def name(self) -> str:
        return "t1"

    @property
    def min_severity(self) -> int:
        return 0

    async def deliver(self, alert: Alert) -> None: ...
    async def deliver_digest(self, alerts: Sequence[Alert]) -> None: ...


@dataclass
class _Dist:
    name: str
    version: str = "1.0.0"


@dataclass
class _EntryPoint:
    name: str
    group: str
    _factory: object
    dist: _Dist

    def load(self) -> object:
        return self._factory


def _resolver(mapping: dict[str, list[_EntryPoint]]):
    def resolve(*, group: str) -> list[_EntryPoint]:
        return mapping.get(group, [])

    return resolve


@pytest.mark.unit
async def test_disabled_returns_empty_inventory_and_skips_manager() -> None:
    manager = ReceiverManager()
    inventory = await load_and_wire_plugins(
        PluginsConfig(enabled=False),
        manager=manager,
        entry_points=_resolver({}),
    )
    assert inventory.entries() == ()
    assert manager._receivers == {}


@pytest.mark.unit
async def test_registers_and_starts_plugin_receivers() -> None:
    recv = _GoodReceiver()
    mapping = {
        PluginGroup.RECEIVERS.value: [
            _EntryPoint(
                name="acme-receiver",
                group=PluginGroup.RECEIVERS.value,
                _factory=lambda: recv,
                dist=_Dist(name="acme"),
            )
        ]
    }
    manager = ReceiverManager()
    inventory = await load_and_wire_plugins(
        PluginsConfig(enabled=True),
        manager=manager,
        entry_points=_resolver(mapping),
    )

    assert recv.started  # lifecycle started it explicitly
    assert "acme-receiver" in manager._receivers
    row = {e.id: e for e in inventory.entries()}["seerflow.receivers:acme-receiver"]
    assert row.status is PluginStatus.STARTED
    assert row.version == "1.0.0"


@pytest.mark.unit
async def test_stop_plugin_lifecycle_stops_started_receivers() -> None:
    recv = _GoodReceiver()
    mapping = {
        PluginGroup.RECEIVERS.value: [
            _EntryPoint(
                name="acme-receiver",
                group=PluginGroup.RECEIVERS.value,
                _factory=lambda: recv,
                dist=_Dist(name="acme"),
            )
        ]
    }
    manager = ReceiverManager()
    inventory = await load_and_wire_plugins(
        PluginsConfig(enabled=True),
        manager=manager,
        entry_points=_resolver(mapping),
    )

    await stop_plugin_lifecycle(inventory)

    assert recv.stopped
    row = {e.id: e for e in inventory.entries()}["seerflow.receivers:acme-receiver"]
    assert row.status is PluginStatus.STOPPED


@pytest.mark.unit
async def test_collision_with_builtin_receiver_is_rejected() -> None:
    recv = _GoodReceiver()
    mapping = {
        PluginGroup.RECEIVERS.value: [
            _EntryPoint(
                name="syslog",
                group=PluginGroup.RECEIVERS.value,
                _factory=lambda: recv,
                dist=_Dist(name="acme"),
            )
        ]
    }
    manager = ReceiverManager()
    builtin = _GoodReceiver()
    manager.register("syslog", builtin)

    inventory = await load_and_wire_plugins(
        PluginsConfig(enabled=True),
        manager=manager,
        entry_points=_resolver(mapping),
    )

    # Built-in preserved; the colliding plugin is loaded but not registered/started.
    assert manager._receivers["syslog"] is builtin
    assert not recv.started
    # Still observable in the inventory as LOADED (registration was rejected).
    row = {e.id: e for e in inventory.entries()}["seerflow.receivers:syslog"]
    assert row.status is PluginStatus.LOADED
