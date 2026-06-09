"""Apply a :class:`LoadedPlugins` inventory to Seerflow's wiring seams (S-369).

These are thin adapters over the public registration APIs —
``ReceiverManager.register``, ``NotificationRouter.register_target``. S-370
hardened the receiver path with a collision guard (``register(...,
replace=False)``) and wired full storage-backend config dispatch through
:func:`find_storage_backend` (see :func:`seerflow.storage.connect_storage`).

Registration is best-effort and isolated: a name collision (the receiver
guard's ``False`` return or the router's ``ValueError``) is logged and the
offending plugin is skipped rather than aborting the batch.
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

    Uses :meth:`ReceiverManager.register`'s collision guard
    (``replace=False``, S-370): a plugin whose entry-point name collides with
    an already-registered source (e.g. a built-in ``"syslog"``) is **rejected**
    — the existing source is preserved, the collision is logged at WARNING,
    and the rejected name is dropped from the returned tuple. This closes the
    S-369 "shadow + warn" deferral: a third-party receiver can no longer
    silently take over a built-in source id.
    """
    registered: list[str] = []
    for record in loaded.receivers:
        receiver: Receiver = record.instance
        if not manager.register(record.name, receiver, replace=False):
            _log.warning(
                "Skipping plugin receiver %r (from %s): name collides with an "
                "already-registered source",
                record.name,
                record.distribution,
            )
            continue
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
