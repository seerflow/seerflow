"""Entry-point plugin loader (S-369) — the open-core extension seam.

Discovers third-party distributions that expose factories for Seerflow's
public, ``@runtime_checkable`` Protocols via the documented entry-point groups
(see :mod:`seerflow.plugins.groups`), validates each produced instance
structurally, and returns an immutable inventory the existing wiring registers
by name.

Security / trust boundary
-------------------------
Entry-point plugins execute **arbitrary third-party Python in-process**. The
loader's guarantees are deliberately narrow:

* It only ever resolves **already-installed** distributions through
  :func:`importlib.metadata.entry_points`. It never downloads, fetches, or
  installs remote code.
* Discovery is **opt-in** (``plugins.enabled`` defaults to False) and bounded
  by an operator-controlled group allow-list (``plugins.groups``).
* Each plugin is loaded behind per-plugin failure isolation: an import error,
  a raising factory, a non-callable value, or a Protocol mismatch is logged
  with a message naming the offending entry point and then **skipped** — it
  never crashes the loader or prevents sibling plugins from loading.

Heavier lifecycle hardening (sandboxing, crash containment, version pinning)
is out of scope here and tracked by S-370.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points as _stdlib_entry_points
from typing import TYPE_CHECKING, Protocol

from seerflow.plugins.groups import PluginGroup, protocol_for_group
from seerflow.plugins.records import LoadedPlugins, PluginRecord

if TYPE_CHECKING:
    from collections.abc import Iterable

    from seerflow.config import PluginsConfig

_log = logging.getLogger(__name__)


class _EntryPointLike(Protocol):  # pragma: no cover - structural typing only
    """Subset of :class:`importlib.metadata.EntryPoint` the loader relies on."""

    name: str
    group: str

    def load(self) -> object: ...


class _EntryPointsResolver(Protocol):  # pragma: no cover - structural typing only
    """Callable shape of :func:`importlib.metadata.entry_points`."""

    def __call__(self, *, group: str) -> Iterable[_EntryPointLike]: ...


def _default_entry_points(*, group: str) -> Iterable[_EntryPointLike]:
    return _stdlib_entry_points(group=group)


def _distribution_name(ep: _EntryPointLike) -> str:
    """Best-effort distribution name for ``ep`` (``"unknown"`` if absent)."""
    dist = getattr(ep, "dist", None)
    name = getattr(dist, "name", None)
    return name if isinstance(name, str) and name else "unknown"


def _load_one(group: PluginGroup, ep: _EntryPointLike) -> PluginRecord | None:
    """Load, instantiate, and Protocol-validate one entry point.

    Returns the built :class:`PluginRecord`, or ``None`` (logged) when the
    plugin fails to import, raises, is not callable, or does not satisfy its
    group's Protocol. Never propagates plugin errors.
    """
    label = f"{group.value}:{ep.name}"
    try:
        factory = ep.load()
    except Exception:
        _log.warning("Skipping plugin %r: entry point failed to load", label, exc_info=True)
        return None
    if not callable(factory):
        _log.warning("Skipping plugin %r: entry-point value is not a callable factory", label)
        return None
    try:
        instance = factory()
    except Exception:
        _log.warning("Skipping plugin %r: factory raised", label, exc_info=True)
        return None
    protocol = protocol_for_group(group)
    if not isinstance(instance, protocol):
        _log.warning(
            "Skipping plugin %r: instance does not satisfy %s",
            label,
            protocol.__name__,
        )
        return None
    return PluginRecord(
        group=group,
        name=ep.name,
        distribution=_distribution_name(ep),
        instance=instance,
    )


def load_plugins(
    config: PluginsConfig,
    *,
    entry_points: _EntryPointsResolver = _default_entry_points,
) -> LoadedPlugins:
    """Discover + validate plugins per ``config``; return an immutable inventory.

    When ``config.enabled`` is False the loader returns an empty inventory and
    never touches entry points. ``entry_points`` is injectable for testing;
    it defaults to :func:`importlib.metadata.entry_points`.
    """
    if not config.enabled:
        return LoadedPlugins()
    records: list[PluginRecord] = []
    for group_name in config.groups:
        group = PluginGroup(group_name)
        for ep in entry_points(group=group_name):
            record = _load_one(group, ep)
            if record is not None:
                records.append(record)
    return LoadedPlugins(records=tuple(records))
