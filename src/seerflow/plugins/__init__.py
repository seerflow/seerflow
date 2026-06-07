"""Entry-point plugin loader (S-369) — the open-core extension seam.

This package lets third-party distributions extend Seerflow through its
public, ``@runtime_checkable`` Protocols (``Receiver``, ``DeliveryTarget``,
``StorageBackend``) **without forking core**. Plugins are discovered via
documented :mod:`importlib.metadata` entry-point groups, validated
structurally, and registered into the existing ``ReceiverManager`` /
``NotificationRouter`` seams.

Discovery is opt-in (``plugins.enabled`` defaults to False) and only ever
resolves already-installed distributions — see :mod:`seerflow.plugins.loader`
for the full trust-boundary contract. No Pro logic and no license gating live
here; this is purely the public extension surface (NFR-008).

Public API
----------
* :func:`load_plugins` — discover + validate the configured plugins.
* :class:`LoadedPlugins` / :class:`PluginRecord` — immutable inventory.
* :class:`PluginGroup` / :data:`KNOWN_PLUGIN_GROUPS` — the documented groups.
* :func:`register_plugin_receivers` / :func:`register_plugin_targets` /
  :func:`find_storage_backend` — wiring adapters.
"""

from __future__ import annotations

from seerflow.plugins.groups import (
    KNOWN_PLUGIN_GROUPS,
    PluginGroup,
    protocol_for_group,
)
from seerflow.plugins.loader import load_plugins
from seerflow.plugins.records import LoadedPlugins, PluginRecord
from seerflow.plugins.registration import (
    find_storage_backend,
    register_plugin_receivers,
    register_plugin_targets,
)

__all__ = [
    "KNOWN_PLUGIN_GROUPS",
    "LoadedPlugins",
    "PluginGroup",
    "PluginRecord",
    "find_storage_backend",
    "load_plugins",
    "protocol_for_group",
    "register_plugin_receivers",
    "register_plugin_targets",
]
