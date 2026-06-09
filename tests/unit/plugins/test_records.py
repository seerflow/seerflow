"""Unit tests for immutable plugin inventory records (S-369)."""

from __future__ import annotations

import dataclasses

import pytest

from seerflow.plugins.groups import PluginGroup
from seerflow.plugins.records import LoadedPlugins, PluginRecord


def _record(group: PluginGroup, name: str) -> PluginRecord:
    return PluginRecord(
        group=group,
        name=name,
        distribution="acme-plugin",
        instance=object(),
    )


@pytest.mark.unit
def test_plugin_record_is_frozen() -> None:
    rec = _record(PluginGroup.RECEIVERS, "r1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.name = "other"  # type: ignore[misc]


@pytest.mark.unit
def test_plugin_record_version_defaults_to_unknown() -> None:
    rec = _record(PluginGroup.RECEIVERS, "r1")
    assert rec.version == "unknown"


@pytest.mark.unit
def test_plugin_record_carries_declared_version() -> None:
    rec = PluginRecord(
        group=PluginGroup.RECEIVERS,
        name="r1",
        distribution="acme-plugin",
        version="1.2.3",
        instance=object(),
    )
    assert rec.version == "1.2.3"


@pytest.mark.unit
def test_empty_loaded_plugins_is_default() -> None:
    loaded = LoadedPlugins()
    assert loaded.count == 0
    assert loaded.receivers == ()
    assert loaded.delivery_targets == ()
    assert loaded.storage_backends == ()
    assert loaded.names() == ()


@pytest.mark.unit
def test_loaded_plugins_is_frozen() -> None:
    loaded = LoadedPlugins()
    with pytest.raises(dataclasses.FrozenInstanceError):
        loaded.records = ()  # type: ignore[misc]


@pytest.mark.unit
def test_filtered_views_partition_by_group() -> None:
    r1 = _record(PluginGroup.RECEIVERS, "r1")
    t1 = _record(PluginGroup.DELIVERY_TARGETS, "t1")
    s1 = _record(PluginGroup.STORAGE_BACKENDS, "s1")
    loaded = LoadedPlugins(records=(r1, t1, s1))

    assert loaded.count == 3
    assert loaded.receivers == (r1,)
    assert loaded.delivery_targets == (t1,)
    assert loaded.storage_backends == (s1,)


@pytest.mark.unit
def test_names_lists_group_qualified_inventory() -> None:
    r1 = _record(PluginGroup.RECEIVERS, "r1")
    t1 = _record(PluginGroup.DELIVERY_TARGETS, "t1")
    loaded = LoadedPlugins(records=(r1, t1))
    assert loaded.names() == (
        "seerflow.receivers:r1",
        "seerflow.delivery_targets:t1",
    )
