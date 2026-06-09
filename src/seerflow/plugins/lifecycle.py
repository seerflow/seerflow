"""Observable plugin lifecycle + start/stop failure isolation (S-370).

S-369 shipped per-plugin isolation at *load* time. This module extends the
same guarantee to **lifecycle** (start/stop) and makes the result observable:

* :class:`PluginInventory` holds the id → :class:`PluginStatus` map over an
  immutable :class:`~seerflow.plugins.records.LoadedPlugins`. Records stay
  frozen (the project immutable-data rule); status is tracked beside them so
  the discovery artifact is never mutated.
* :func:`start_plugin_receivers` / :func:`stop_plugin_receivers` drive only
  the ``seerflow.receivers`` group plugins — the sole public Protocol that
  declares ``start()`` / ``stop()``. Each call is wrapped in per-plugin
  isolation: a raising ``start()`` / ``stop()`` is logged with the offending
  ``group:name`` label, the record is marked :attr:`PluginStatus.FAILED`, and
  sibling plugins still run. Errors are never silently swallowed.

These helpers *compose* with :class:`~seerflow.receivers.manager.ReceiverManager`
(which already isolates per-receiver failures for the whole pipeline); they do
not re-implement an event loop. They exist so plugin lifecycle outcomes surface
in the ``GET /api/v1/plugins`` inventory (AC-4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from seerflow.plugins.groups import protocol_for_group

if TYPE_CHECKING:
    from seerflow.plugins.records import LoadedPlugins, PluginRecord

_log = logging.getLogger(__name__)


class PluginStatus(StrEnum):
    """Observable lifecycle state of a single plugin (AC-4 ``status`` field)."""

    LOADED = "loaded"
    STARTED = "started"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginInventoryEntry:
    """One immutable inventory row exposed by the ``/api/v1/plugins`` route."""

    id: str
    version: str
    protocol: str
    status: PluginStatus


def _record_id(record: PluginRecord) -> str:
    """Namespaced ``group:name`` id for ``record`` (AC-1)."""
    return f"{record.group.value}:{record.name}"


class PluginInventory:
    """Mutable id → status registry over an immutable ``LoadedPlugins``.

    The wrapped :class:`LoadedPlugins` is the source of truth for *which*
    plugins exist (frozen); this registry tracks their evolving lifecycle
    status without mutating any frozen record. :meth:`entries` rebuilds an
    immutable tuple of rows on every call, so the observable inventory is
    side-effect free.
    """

    __slots__ = ("_loaded", "_status")

    def __init__(self, loaded: LoadedPlugins) -> None:
        self._loaded = loaded
        self._status: dict[str, PluginStatus] = {
            _record_id(r): PluginStatus.LOADED for r in loaded.records
        }

    @property
    def loaded(self) -> LoadedPlugins:
        """The immutable discovery inventory this registry tracks."""
        return self._loaded

    def status_of(self, plugin_id: str) -> PluginStatus | None:
        """Current status for ``plugin_id`` (``None`` if not tracked)."""
        return self._status.get(plugin_id)

    def _set_status(self, plugin_id: str, status: PluginStatus) -> None:
        self._status[plugin_id] = status

    def entries(self) -> tuple[PluginInventoryEntry, ...]:
        """Immutable ``(id, version, protocol, status)`` rows in discovery order."""
        return tuple(
            PluginInventoryEntry(
                id=_record_id(r),
                version=r.version,
                protocol=protocol_for_group(r.group).__name__,
                status=self._status[_record_id(r)],
            )
            for r in self._loaded.records
        )


async def start_plugin_receivers(
    inventory: PluginInventory,
    *,
    only: frozenset[str] | None = None,
) -> None:
    """Start receiver-group plugins behind per-plugin isolation.

    A receiver whose ``start()`` raises is logged (with ``exc_info``) and
    marked :attr:`PluginStatus.FAILED`; siblings still start. Non-receiver
    groups are skipped (they have no lifecycle methods) and keep status
    :attr:`PluginStatus.LOADED`.

    ``only`` restricts the set of started plugins to the given namespaced ids
    (used by the pipeline so a receiver whose registration was rejected on a
    name collision is never started — it stays :attr:`PluginStatus.LOADED`).
    ``None`` (default) starts every receiver plugin.
    """
    for record in inventory.loaded.receivers:
        plugin_id = _record_id(record)
        if only is not None and plugin_id not in only:
            continue
        try:
            await record.instance.start()
        except Exception:
            _log.warning("Plugin %r failed to start", plugin_id, exc_info=True)
            inventory._set_status(plugin_id, PluginStatus.FAILED)
            continue
        inventory._set_status(plugin_id, PluginStatus.STARTED)


async def stop_plugin_receivers(
    inventory: PluginInventory,
    *,
    only: frozenset[str] | None = None,
) -> None:
    """Stop receiver-group plugins behind per-plugin isolation.

    A receiver whose ``stop()`` raises is logged (with ``exc_info``) and
    marked :attr:`PluginStatus.FAILED`; siblings still stop. ``only`` mirrors
    :func:`start_plugin_receivers` — restrict to the given namespaced ids.
    Only plugins currently :attr:`PluginStatus.STARTED` are stopped, so a
    receiver that never started (rejected / failed) is left untouched.
    """
    for record in inventory.loaded.receivers:
        plugin_id = _record_id(record)
        if only is not None and plugin_id not in only:
            continue
        if inventory.status_of(plugin_id) is not PluginStatus.STARTED:
            continue
        try:
            await record.instance.stop()
        except Exception:
            _log.warning("Plugin %r failed to stop", plugin_id, exc_info=True)
            inventory._set_status(plugin_id, PluginStatus.FAILED)
            continue
        inventory._set_status(plugin_id, PluginStatus.STOPPED)
