"""Async bridge for Drain3 template persistence via ModelStore."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from seerflow.parsing.drain import DrainParser
    from seerflow.storage.protocols import ModelStore

_log = logging.getLogger(__name__)

_DEFAULT_KEY: Final[str] = "drain3:global"


async def save_drain_state(
    parser: DrainParser,
    store: ModelStore,
    *,
    key: str = _DEFAULT_KEY,
) -> None:
    """Save current Drain3 template state to *store*.

    Serialization is handled by ``DrainParser.get_state()``.
    Exceptions from ``ModelStore.save_state()`` propagate to the caller.
    """
    data = parser.get_state()
    await store.save_state(key, data)
    _log.info(
        "Saved Drain3 state (%d templates, %d bytes) to key %r",
        parser.template_count,
        len(data),
        key,
    )


async def load_drain_state(
    parser: DrainParser,
    store: ModelStore,
    *,
    key: str = _DEFAULT_KEY,
) -> bool:
    """Load persisted Drain3 state into *parser*.

    Returns:
        ``True`` if state was loaded successfully, ``False`` if no
        persisted state exists (first run) or deserialization failed
        (parser starts fresh).
    """
    data = await store.load_state(key)
    if data is None:
        _log.info("No persisted Drain3 state for key %r (first run)", key)
        return False
    try:
        parser.load_state(data)
    except ValueError:
        _log.warning(
            "Failed to deserialize Drain3 state for key %r; starting fresh",
            key,
            exc_info=True,
        )
        return False
    _log.info(
        "Restored Drain3 state (%d templates) from key %r",
        parser.template_count,
        key,
    )
    return True
