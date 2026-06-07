"""Immutable plugin inventory records (S-369).

The loader returns a frozen :class:`LoadedPlugins` aggregate of frozen
:class:`PluginRecord` entries. Immutability keeps the observable inventory
(AC-5) side-effect free and aligns with the project immutable-data rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seerflow.plugins.groups import PluginGroup


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginRecord:
    """One discovered + validated plugin.

    ``instance`` is the Protocol-conforming object produced by the entry-point
    factory; its concrete type is plugin-defined, hence ``Any``.
    """

    group: PluginGroup
    name: str
    distribution: str
    instance: Any


@dataclass(frozen=True, slots=True)
class LoadedPlugins:
    """Frozen aggregate of all validated plugin records."""

    records: tuple[PluginRecord, ...] = field(default_factory=tuple)

    @property
    def count(self) -> int:
        """Total number of validated plugins."""
        return len(self.records)

    def _by_group(self, group: PluginGroup) -> tuple[PluginRecord, ...]:
        return tuple(r for r in self.records if r.group is group)

    @property
    def receivers(self) -> tuple[PluginRecord, ...]:
        """Records in the ``seerflow.receivers`` group."""
        return self._by_group(PluginGroup.RECEIVERS)

    @property
    def delivery_targets(self) -> tuple[PluginRecord, ...]:
        """Records in the ``seerflow.delivery_targets`` group."""
        return self._by_group(PluginGroup.DELIVERY_TARGETS)

    @property
    def storage_backends(self) -> tuple[PluginRecord, ...]:
        """Records in the ``seerflow.storage_backends`` group."""
        return self._by_group(PluginGroup.STORAGE_BACKENDS)

    def names(self) -> tuple[str, ...]:
        """Group-qualified ``group:name`` inventory in discovery order."""
        return tuple(f"{r.group.value}:{r.name}" for r in self.records)
