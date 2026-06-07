"""Plugin entry-point groups and their public Protocol mapping (S-369).

Each documented entry-point *group* corresponds to exactly one public,
``@runtime_checkable`` Protocol that a third-party distribution may implement.
The group names are part of Seerflow's public contract — community plugins
declare them in their own ``pyproject.toml`` ``[project.entry-points]`` table:

    [project.entry-points."seerflow.receivers"]
    my-receiver = "my_pkg:make_receiver"

    [project.entry-points."seerflow.delivery_targets"]
    my-sink = "my_pkg:make_target"

    [project.entry-points."seerflow.storage_backends"]
    my-store = "my_pkg:make_backend"

The entry-point value must be a **zero-argument callable factory** returning a
Protocol-conforming instance. The loader validates the produced instance via
``isinstance`` against the mapped Protocol.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class PluginGroup(StrEnum):
    """Documented entry-point group names (public API)."""

    RECEIVERS = "seerflow.receivers"
    DELIVERY_TARGETS = "seerflow.delivery_targets"
    STORAGE_BACKENDS = "seerflow.storage_backends"


# Public, stable set of group names the loader knows how to validate.
KNOWN_PLUGIN_GROUPS: frozenset[str] = frozenset(g.value for g in PluginGroup)


def protocol_for_group(group: PluginGroup | str) -> type[Any]:
    """Return the runtime-checkable Protocol class for ``group``.

    Protocols are imported lazily so importing this module stays cheap and free
    of the ``config``/``alerting``/``storage`` import cycles.

    Raises:
        ValueError: When ``group`` is not one of ``KNOWN_PLUGIN_GROUPS``.
    """
    name = group.value if isinstance(group, PluginGroup) else group
    if name == PluginGroup.RECEIVERS.value:
        from seerflow.receivers.base import Receiver

        return Receiver
    if name == PluginGroup.DELIVERY_TARGETS.value:
        from seerflow.alerting.target import DeliveryTarget

        return DeliveryTarget
    if name == PluginGroup.STORAGE_BACKENDS.value:
        from seerflow.storage.protocols import StorageBackend

        return StorageBackend
    msg = f"unknown plugin group {name!r}; known: {sorted(KNOWN_PLUGIN_GROUPS)}"
    raise ValueError(msg)
