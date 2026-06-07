"""Integration test: third-party plugins register with zero core changes (S-369).

Proves AC-2 end-to-end. A fake ``entry_points`` resolver exposes factories
defined *here in the test* (i.e. outside ``src/seerflow``); after
``load_plugins`` + ``register_plugin_*`` the real ``ReceiverManager`` and a
real ``NotificationRouter`` hold the plugin instances — without editing any
core module. Also exercises rejection of an incompatible plugin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from seerflow.alerting.router import NotificationRouter
from seerflow.config import PluginsConfig
from seerflow.plugins import (
    load_plugins,
    register_plugin_receivers,
    register_plugin_targets,
)
from seerflow.plugins.groups import PluginGroup
from seerflow.receivers.manager import ReceiverManager

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert


# --- Third-party-style plugin implementations (live outside src/seerflow) --- #


class CommunityReceiver:
    """A community-authored Receiver, structurally typed to the Protocol."""

    def __init__(self) -> None:
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    def is_healthy(self) -> bool:
        return self.started


class CommunityTarget:
    """A community-authored DeliveryTarget."""

    def __init__(self, name: str = "community-sink") -> None:
        self._name = name
        self.delivered: list[Alert] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def min_severity(self) -> int:
        return 0

    async def deliver(self, alert: Alert) -> None:
        self.delivered.append(alert)

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        self.delivered.extend(alerts)


class BrokenReceiver:
    """Incompatible: missing ``is_healthy`` — must be rejected."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...


@dataclass
class _Dist:
    name: str


@dataclass
class _EntryPoint:
    name: str
    group: str
    target: object
    dist: _Dist

    def load(self) -> object:
        return self.target


def _resolver(mapping: dict[str, list[_EntryPoint]]):
    def resolve(*, group: str) -> list[_EntryPoint]:
        return mapping.get(group, [])

    return resolve


@pytest.mark.integration
def test_plugin_receiver_and_target_register_zero_core_changes() -> None:
    mapping = {
        PluginGroup.RECEIVERS.value: [
            _EntryPoint(
                name="community-receiver",
                group=PluginGroup.RECEIVERS.value,
                target=lambda: CommunityReceiver(),
                dist=_Dist(name="community-plugins"),
            )
        ],
        PluginGroup.DELIVERY_TARGETS.value: [
            _EntryPoint(
                name="community-sink",
                group=PluginGroup.DELIVERY_TARGETS.value,
                target=lambda: CommunityTarget(),
                dist=_Dist(name="community-plugins"),
            )
        ],
    }

    loaded = load_plugins(PluginsConfig(enabled=True), entry_points=_resolver(mapping))
    assert loaded.count == 2

    manager = ReceiverManager()
    router = NotificationRouter(targets=())

    receiver_names = register_plugin_receivers(manager, loaded)
    target_names = register_plugin_targets(router, loaded)

    assert receiver_names == ("community-receiver",)
    assert target_names == ("community-sink",)
    # The real manager now holds the community receiver instance.
    assert isinstance(manager._receivers["community-receiver"], CommunityReceiver)
    # The real router now addresses the community target by name.
    assert router._targets["community-sink"].name == "community-sink"


@pytest.mark.integration
def test_incompatible_plugin_rejected_with_clear_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mapping = {
        PluginGroup.RECEIVERS.value: [
            _EntryPoint(
                name="broken",
                group=PluginGroup.RECEIVERS.value,
                target=lambda: BrokenReceiver(),
                dist=_Dist(name="broken-plugins"),
            )
        ]
    }
    with caplog.at_level("WARNING"):
        loaded = load_plugins(PluginsConfig(enabled=True), entry_points=_resolver(mapping))

    assert loaded.count == 0
    messages = " ".join(r.message for r in caplog.records)
    assert "broken" in messages
    assert "Receiver" in messages
