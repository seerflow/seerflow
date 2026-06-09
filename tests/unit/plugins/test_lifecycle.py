"""Unit tests for plugin lifecycle status tracking + isolation (S-370)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.plugins.groups import PluginGroup
from seerflow.plugins.lifecycle import (
    PluginInventory,
    PluginStatus,
    start_plugin_receivers,
    stop_plugin_receivers,
)
from seerflow.plugins.records import LoadedPlugins, PluginRecord

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


class _BoomReceiver:
    def __init__(self, *, fail_start: bool = False, fail_stop: bool = False) -> None:
        self._fail_start = fail_start
        self._fail_stop = fail_stop

    async def start(self) -> None:
        if self._fail_start:
            msg = "start boom"
            raise RuntimeError(msg)

    async def stop(self) -> None:
        if self._fail_stop:
            msg = "stop boom"
            raise RuntimeError(msg)

    def is_healthy(self) -> bool:
        return True


class _GoodTarget:
    @property
    def name(self) -> str:
        return "t1"

    @property
    def min_severity(self) -> int:
        return 0

    async def deliver(self, alert: Alert) -> None: ...
    async def deliver_digest(self, alerts: Sequence[Alert]) -> None: ...


def _receiver_record(name: str, instance: object) -> PluginRecord:
    return PluginRecord(
        group=PluginGroup.RECEIVERS,
        name=name,
        distribution="acme",
        version="1.0.0",
        instance=instance,
    )


def _target_record(name: str, instance: object) -> PluginRecord:
    return PluginRecord(
        group=PluginGroup.DELIVERY_TARGETS,
        name=name,
        distribution="acme",
        version="2.0.0",
        instance=instance,
    )


@pytest.mark.unit
def test_inventory_starts_all_loaded() -> None:
    loaded = LoadedPlugins(
        records=(
            _receiver_record("r1", _GoodReceiver()),
            _target_record("t1", _GoodTarget()),
        )
    )
    inv = PluginInventory(loaded)

    rows = inv.entries()
    assert len(rows) == 2
    by_id = {row.id: row for row in rows}
    assert by_id["seerflow.receivers:r1"].status is PluginStatus.LOADED
    assert by_id["seerflow.receivers:r1"].version == "1.0.0"
    assert by_id["seerflow.receivers:r1"].protocol == "Receiver"
    assert by_id["seerflow.delivery_targets:t1"].protocol == "DeliveryTarget"
    assert by_id["seerflow.delivery_targets:t1"].version == "2.0.0"


@pytest.mark.unit
def test_empty_inventory_has_no_entries() -> None:
    inv = PluginInventory(LoadedPlugins())
    assert inv.entries() == ()


@pytest.mark.unit
def test_start_marks_started_and_isolates_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    good = _GoodReceiver()
    boom = _BoomReceiver(fail_start=True)
    loaded = LoadedPlugins(
        records=(
            _receiver_record("boom", boom),
            _receiver_record("good", good),
        )
    )
    inv = PluginInventory(loaded)

    with caplog.at_level("WARNING"):
        import asyncio

        asyncio.run(start_plugin_receivers(inv))

    assert good.started  # sibling still started despite boom raising
    by_id = {row.id: row.status for row in inv.entries()}
    assert by_id["seerflow.receivers:good"] is PluginStatus.STARTED
    assert by_id["seerflow.receivers:boom"] is PluginStatus.FAILED
    assert any("boom" in r.message for r in caplog.records)


@pytest.mark.unit
def test_stop_marks_stopped_and_isolates_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import asyncio

    good = _GoodReceiver()
    boom = _BoomReceiver(fail_stop=True)
    loaded = LoadedPlugins(
        records=(
            _receiver_record("boom", boom),
            _receiver_record("good", good),
        )
    )
    inv = PluginInventory(loaded)

    asyncio.run(start_plugin_receivers(inv))
    with caplog.at_level("WARNING"):
        asyncio.run(stop_plugin_receivers(inv))

    assert good.stopped
    by_id = {row.id: row.status for row in inv.entries()}
    assert by_id["seerflow.receivers:good"] is PluginStatus.STOPPED
    assert by_id["seerflow.receivers:boom"] is PluginStatus.FAILED
    assert any("boom" in r.message for r in caplog.records)


@pytest.mark.unit
def test_stop_skips_never_started_receiver() -> None:
    import asyncio

    recv = _GoodReceiver()
    loaded = LoadedPlugins(records=(_receiver_record("r1", recv),))
    inv = PluginInventory(loaded)

    # Never started → stop is a no-op, status stays LOADED, stop() not called.
    asyncio.run(stop_plugin_receivers(inv))

    assert not recv.stopped
    by_id = {row.id: row.status for row in inv.entries()}
    assert by_id["seerflow.receivers:r1"] is PluginStatus.LOADED


@pytest.mark.unit
def test_start_and_stop_only_filter_excludes_others() -> None:
    import asyncio

    keep = _GoodReceiver()
    skip = _GoodReceiver()
    loaded = LoadedPlugins(
        records=(_receiver_record("keep", keep), _receiver_record("skip", skip))
    )
    inv = PluginInventory(loaded)
    only = frozenset({"seerflow.receivers:keep"})

    asyncio.run(start_plugin_receivers(inv, only=only))
    asyncio.run(stop_plugin_receivers(inv, only=only))

    assert keep.started and keep.stopped
    assert not skip.started and not skip.stopped
    by_id = {row.id: row.status for row in inv.entries()}
    assert by_id["seerflow.receivers:keep"] is PluginStatus.STOPPED
    assert by_id["seerflow.receivers:skip"] is PluginStatus.LOADED


@pytest.mark.unit
def test_lifecycle_ignores_non_receiver_groups() -> None:
    import asyncio

    target = _GoodTarget()
    loaded = LoadedPlugins(records=(_target_record("t1", target),))
    inv = PluginInventory(loaded)

    asyncio.run(start_plugin_receivers(inv))
    asyncio.run(stop_plugin_receivers(inv))

    # Targets have no start/stop; their status stays LOADED.
    by_id = {row.id: row.status for row in inv.entries()}
    assert by_id["seerflow.delivery_targets:t1"] is PluginStatus.LOADED
