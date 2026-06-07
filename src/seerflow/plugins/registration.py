"""Apply a :class:`LoadedPlugins` inventory to Seerflow's wiring seams (S-369).

These are thin adapters over the *existing* public registration APIs —
``ReceiverManager.register``, ``NotificationRouter.register_target`` — so a
plugin Receiver or DeliveryTarget participates with **zero core changes**
(AC-2). Storage-backend plugins are exposed via a lookup helper; full config
dispatch wiring is intentionally left to a follow-up (S-370) per the story.

Registration is best-effort and isolated: a duplicate name (the router's
``ValueError``) is logged and skipped rather than aborting the batch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from seerflow.alerting.router import NotificationRouter
    from seerflow.alerting.target import DeliveryTarget
    from seerflow.plugins.records import LoadedPlugins
    from seerflow.receivers.base import Receiver
    from seerflow.receivers.manager import ReceiverManager

_log = logging.getLogger(__name__)


def register_plugin_receivers(
    manager: ReceiverManager,
    loaded: LoadedPlugins,
) -> tuple[str, ...]:
    """Register every plugin receiver into ``manager``; return the names used.

    ``ReceiverManager.register`` keys receivers by ``source_id`` and overwrites
    on collision (its existing contract). A plugin whose entry-point name
    matches a built-in source id (e.g. ``"syslog"``) therefore *shadows* the
    built-in; the collision is logged at WARNING so operators can spot it.
    Adding a collision guard to the manager is deferred to S-370 to keep this
    story's "zero core changes" (AC-2) guarantee intact.
    """
    registered: list[str] = []
    for record in loaded.receivers:
        receiver: Receiver = record.instance
        if record.name in manager._receivers:
            _log.warning(
                "Plugin receiver %r shadows an already-registered source (from %s)",
                record.name,
                record.distribution,
            )
        manager.register(record.name, receiver)
        registered.append(record.name)
        _log.info("Registered plugin receiver %r (from %s)", record.name, record.distribution)
    return tuple(registered)


def register_plugin_targets(
    router: NotificationRouter,
    loaded: LoadedPlugins,
) -> tuple[str, ...]:
    """Register every plugin delivery target into ``router``; return names used.

    A duplicate target name raises ``ValueError`` inside the router; that is
    caught, logged, and skipped so one collision does not abort the batch.
    """
    registered: list[str] = []
    for record in loaded.delivery_targets:
        target: DeliveryTarget = record.instance
        try:
            router.register_target(target)
        except ValueError as exc:
            _log.warning("Skipping plugin target %r: %s", record.name, exc)
            continue
        registered.append(record.name)
        _log.info("Registered plugin target %r (from %s)", record.name, record.distribution)
    return tuple(registered)


def find_storage_backend(loaded: LoadedPlugins, name: str) -> Any:
    """Return the storage-backend plugin instance named ``name``, or ``None``."""
    for record in loaded.storage_backends:
        if record.name == name:
            return record.instance
    return None
