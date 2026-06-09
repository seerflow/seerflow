"""Load + wire entry-point plugins into the live pipeline (S-370 Task 6).

A single focused seam the live runner (:mod:`seerflow.pipeline.run`) calls to
turn ``plugins`` config into a registered, lifecycle-started, observable
inventory. Kept out of the (already large) ``_run_with_config`` so it is
independently unit-testable and small.

Flow:

1. :func:`~seerflow.plugins.loader.load_plugins` — discover + Protocol-validate
   (per-plugin load isolation; opt-in via ``config.enabled``).
2. :func:`~seerflow.plugins.registration.register_plugin_receivers` — register
   receiver plugins into the live :class:`ReceiverManager` behind the
   collision guard (a name colliding with a built-in source is rejected).
3. :func:`~seerflow.plugins.lifecycle.start_plugin_receivers` — explicitly
   start *only* the receivers that registered (the manager's own ``start()``
   already ran for built-ins by the time this is called), isolating failures.

Returns the :class:`PluginInventory` the ``GET /api/v1/plugins`` route reads.
Delivery-target and storage-backend wiring happen at their own seams
(``connect_storage`` for storage dispatch; the alerting router for targets).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.plugins.lifecycle import (
    PluginInventory,
    start_plugin_receivers,
    stop_plugin_receivers,
)
from seerflow.plugins.loader import load_plugins
from seerflow.plugins.registration import register_plugin_receivers

if TYPE_CHECKING:
    from seerflow.config import PluginsConfig
    from seerflow.plugins.loader import _EntryPointsResolver
    from seerflow.receivers.manager import ReceiverManager


async def load_and_wire_plugins(
    config: PluginsConfig,
    *,
    manager: ReceiverManager,
    entry_points: _EntryPointsResolver | None = None,
) -> PluginInventory:
    """Load plugins, register + start receivers, return the inventory.

    ``entry_points`` is an injectable resolver (test seam); ``None`` uses the
    stdlib default inside :func:`load_plugins`. When ``config.enabled`` is
    False an empty inventory is returned and the manager is never touched.
    """
    loaded = (
        load_plugins(config, entry_points=entry_points)
        if entry_points is not None
        else load_plugins(config)
    )
    inventory = PluginInventory(loaded)
    registered = register_plugin_receivers(manager, loaded)
    await start_plugin_receivers(inventory, only=frozenset(_qualified(registered)))
    return inventory


def _qualified(receiver_names: tuple[str, ...]) -> tuple[str, ...]:
    """Map bare receiver names to their namespaced ``group:name`` ids."""
    from seerflow.plugins.groups import PluginGroup

    return tuple(f"{PluginGroup.RECEIVERS.value}:{name}" for name in receiver_names)


async def stop_plugin_lifecycle(inventory: PluginInventory) -> None:
    """Stop every started receiver plugin in ``inventory`` (shutdown path)."""
    await stop_plugin_receivers(inventory)
