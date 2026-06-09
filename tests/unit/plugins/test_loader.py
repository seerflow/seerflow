"""Unit tests for the entry-point plugin loader (S-369)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from seerflow.config import PluginsConfig
from seerflow.plugins.groups import PluginGroup
from seerflow.plugins.loader import load_plugins

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert


# --------------------------------------------------------------------------- #
# Test doubles: Protocol-conforming and non-conforming plugin objects.
# --------------------------------------------------------------------------- #


class _GoodReceiver:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def is_healthy(self) -> bool:
        return True


class _GoodTarget:
    @property
    def name(self) -> str:
        return "plugin-target"

    @property
    def min_severity(self) -> int:
        return 0

    async def deliver(self, alert: Alert) -> None: ...
    async def deliver_digest(self, alerts: Sequence[Alert]) -> None: ...


class _NotAReceiver:
    """Missing ``is_healthy`` — fails the Receiver Protocol."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...


@dataclass
class _FakeDist:
    name: str
    version: str = "9.9.9"


@dataclass
class _FakeEntryPoint:
    name: str
    group: str
    _factory: object
    dist: _FakeDist

    def load(self) -> object:
        if isinstance(self._factory, Exception):
            raise self._factory
        return self._factory


def _make_resolver(mapping: dict[str, list[_FakeEntryPoint]]):
    """Return an ``entry_points(group=...)`` stand-in over ``mapping``."""

    def resolver(*, group: str) -> list[_FakeEntryPoint]:
        return mapping.get(group, [])

    return resolver


def _good_receiver_ep() -> _FakeEntryPoint:
    return _FakeEntryPoint(
        name="acme-receiver",
        group=PluginGroup.RECEIVERS.value,
        _factory=lambda: _GoodReceiver(),
        dist=_FakeDist(name="acme-plugins"),
    )


def _good_target_ep() -> _FakeEntryPoint:
    return _FakeEntryPoint(
        name="acme-target",
        group=PluginGroup.DELIVERY_TARGETS.value,
        _factory=lambda: _GoodTarget(),
        dist=_FakeDist(name="acme-plugins"),
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_disabled_config_returns_empty_and_skips_discovery() -> None:
    calls: list[str] = []

    def resolver(*, group: str) -> list[_FakeEntryPoint]:
        calls.append(group)
        return []

    loaded = load_plugins(PluginsConfig(enabled=False), entry_points=resolver)

    assert loaded.count == 0
    assert calls == []  # never touched entry points


@pytest.mark.unit
def test_loads_valid_receiver_and_target() -> None:
    resolver = _make_resolver(
        {
            PluginGroup.RECEIVERS.value: [_good_receiver_ep()],
            PluginGroup.DELIVERY_TARGETS.value: [_good_target_ep()],
        }
    )
    loaded = load_plugins(PluginsConfig(enabled=True), entry_points=resolver)

    assert loaded.count == 2
    assert len(loaded.receivers) == 1
    assert len(loaded.delivery_targets) == 1
    assert loaded.receivers[0].name == "acme-receiver"
    assert loaded.receivers[0].distribution == "acme-plugins"
    assert loaded.receivers[0].version == "9.9.9"
    assert isinstance(loaded.receivers[0].instance, _GoodReceiver)


@pytest.mark.unit
def test_missing_distribution_version_falls_back_to_unknown() -> None:
    no_dist_ep = _FakeEntryPoint(
        name="acme-receiver",
        group=PluginGroup.RECEIVERS.value,
        _factory=lambda: _GoodReceiver(),
        dist=None,  # type: ignore[arg-type]
    )
    resolver = _make_resolver({PluginGroup.RECEIVERS.value: [no_dist_ep]})
    loaded = load_plugins(PluginsConfig(enabled=True), entry_points=resolver)

    assert loaded.count == 1
    assert loaded.receivers[0].distribution == "unknown"
    assert loaded.receivers[0].version == "unknown"


@pytest.mark.unit
def test_incompatible_plugin_rejected_without_crash(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bad_ep = _FakeEntryPoint(
        name="broken-receiver",
        group=PluginGroup.RECEIVERS.value,
        _factory=lambda: _NotAReceiver(),
        dist=_FakeDist(name="broken-plugins"),
    )
    resolver = _make_resolver({PluginGroup.RECEIVERS.value: [bad_ep, _good_receiver_ep()]})
    with caplog.at_level("WARNING"):
        loaded = load_plugins(PluginsConfig(enabled=True), entry_points=resolver)

    # The good one still loads; the bad one is skipped.
    assert loaded.count == 1
    assert loaded.receivers[0].name == "acme-receiver"
    assert any("broken-receiver" in r.message for r in caplog.records)


@pytest.mark.unit
def test_factory_raising_is_isolated(caplog: pytest.LogCaptureFixture) -> None:
    def boom() -> object:
        raise RuntimeError("factory exploded")

    raising_ep = _FakeEntryPoint(
        name="raising-receiver",
        group=PluginGroup.RECEIVERS.value,
        _factory=boom,
        dist=_FakeDist(name="raising-plugins"),
    )
    resolver = _make_resolver({PluginGroup.RECEIVERS.value: [raising_ep, _good_receiver_ep()]})
    with caplog.at_level("WARNING"):
        loaded = load_plugins(PluginsConfig(enabled=True), entry_points=resolver)

    assert loaded.count == 1
    assert any("raising-receiver" in r.message for r in caplog.records)


@pytest.mark.unit
def test_entry_point_load_raising_is_isolated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    load_fail_ep = _FakeEntryPoint(
        name="import-error-receiver",
        group=PluginGroup.RECEIVERS.value,
        _factory=ImportError("no such module"),
        dist=_FakeDist(name="bad-import-plugins"),
    )
    resolver = _make_resolver({PluginGroup.RECEIVERS.value: [load_fail_ep]})
    with caplog.at_level("WARNING"):
        loaded = load_plugins(PluginsConfig(enabled=True), entry_points=resolver)

    assert loaded.count == 0
    assert any("import-error-receiver" in r.message for r in caplog.records)


@pytest.mark.unit
def test_group_allow_list_restricts_discovery() -> None:
    calls: list[str] = []

    def resolver(*, group: str) -> list[_FakeEntryPoint]:
        calls.append(group)
        if group == PluginGroup.RECEIVERS.value:
            return [_good_receiver_ep()]
        return [_good_target_ep()]

    loaded = load_plugins(
        PluginsConfig(enabled=True, groups=(PluginGroup.RECEIVERS.value,)),
        entry_points=resolver,
    )

    assert calls == [PluginGroup.RECEIVERS.value]
    assert loaded.count == 1
    assert len(loaded.delivery_targets) == 0


@pytest.mark.unit
def test_non_callable_entry_point_value_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    not_callable_ep = _FakeEntryPoint(
        name="not-callable",
        group=PluginGroup.RECEIVERS.value,
        _factory=_GoodReceiver(),  # an instance, not a zero-arg factory
        dist=_FakeDist(name="weird-plugins"),
    )
    resolver = _make_resolver({PluginGroup.RECEIVERS.value: [not_callable_ep]})
    with caplog.at_level("WARNING"):
        loaded = load_plugins(PluginsConfig(enabled=True), entry_points=resolver)

    assert loaded.count == 0
    assert any("not-callable" in r.message for r in caplog.records)


@pytest.mark.unit
def test_default_resolver_is_stdlib_entry_points() -> None:
    # Enabled but no real seerflow.* plugins installed → empty, no crash.
    loaded = load_plugins(PluginsConfig(enabled=True))
    assert loaded.count == 0
