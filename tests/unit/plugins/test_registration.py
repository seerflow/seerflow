"""Unit tests for plugin registration wiring (S-369)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.alerting.router import NotificationRouter
from seerflow.plugins.groups import PluginGroup
from seerflow.plugins.records import LoadedPlugins, PluginRecord
from seerflow.plugins.registration import (
    find_storage_backend,
    register_plugin_receivers,
    register_plugin_targets,
)
from seerflow.receivers.manager import ReceiverManager

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert


class _FakeReceiver:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def is_healthy(self) -> bool:
        return True


class _FakeTarget:
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def min_severity(self) -> int:
        return 0

    async def deliver(self, alert: Alert) -> None: ...
    async def deliver_digest(self, alerts: Sequence[Alert]) -> None: ...


def _receiver_record(name: str) -> PluginRecord:
    return PluginRecord(
        group=PluginGroup.RECEIVERS,
        name=name,
        distribution="acme",
        instance=_FakeReceiver(),
    )


def _target_record(name: str) -> PluginRecord:
    return PluginRecord(
        group=PluginGroup.DELIVERY_TARGETS,
        name=name,
        distribution="acme",
        instance=_FakeTarget(name),
    )


@pytest.mark.unit
def test_register_plugin_receivers_into_manager() -> None:
    manager = ReceiverManager()
    loaded = LoadedPlugins(records=(_receiver_record("r1"), _receiver_record("r2")))

    registered = register_plugin_receivers(manager, loaded)

    assert registered == ("r1", "r2")
    assert set(manager._receivers) == {"r1", "r2"}


@pytest.mark.unit
def test_register_plugin_receiver_name_collision_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = ReceiverManager()
    manager.register("syslog", _FakeReceiver())
    loaded = LoadedPlugins(records=(_receiver_record("syslog"),))

    with caplog.at_level("WARNING"):
        registered = register_plugin_receivers(manager, loaded)

    assert registered == ("syslog",)
    assert any("shadows" in r.message for r in caplog.records)


@pytest.mark.unit
def test_register_plugin_targets_into_router() -> None:
    router = NotificationRouter(targets=())
    loaded = LoadedPlugins(records=(_target_record("t1"), _target_record("t2")))

    registered = register_plugin_targets(router, loaded)

    assert registered == ("t1", "t2")


@pytest.mark.unit
def test_duplicate_target_name_is_skipped_not_crash(
    caplog: pytest.LogCaptureFixture,
) -> None:
    existing = _FakeTarget("dup")
    router = NotificationRouter(targets=(existing,))
    loaded = LoadedPlugins(records=(_target_record("dup"), _target_record("ok")))

    with caplog.at_level("WARNING"):
        registered = register_plugin_targets(router, loaded)

    assert registered == ("ok",)
    assert any("dup" in r.message for r in caplog.records)


@pytest.mark.unit
def test_find_storage_backend_lookup() -> None:
    instance = object()
    rec = PluginRecord(
        group=PluginGroup.STORAGE_BACKENDS,
        name="acme-store",
        distribution="acme",
        instance=instance,
    )
    loaded = LoadedPlugins(records=(rec,))

    assert find_storage_backend(loaded, "acme-store") is instance
    assert find_storage_backend(loaded, "missing") is None
