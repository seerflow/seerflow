# mypy: disable-error-code="empty-body"
"""Tests for the composite StorageBackend Protocol (S-198).

The composite ``StorageBackend`` Protocol intersects the per-domain stores
(``LogStore``, ``AlertStore``, ``ModelStore``, ``EntityStore``) plus the
write_edge / load_edges subset of ``GraphStore`` that both concrete
backends implement, and adds the lifecycle and template-catalog methods
that CLI entry points and the pipeline need (``close``, ``flush``,
``write_templates``, ``get_templates``).

The composite is intentionally narrower than the union of every per-domain
Protocol because ``get_neighbors`` / ``shortest_path`` / ``get_subgraph``
are delivered by a separate ``GraphBackend`` and neither storage backend
implements them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.config import StorageConfig
from seerflow.storage import StorageBackend, connect_storage
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from pathlib import Path


class TestStorageBackendProtocol:
    """Behavioural tests for the composite StorageBackend Protocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """StorageBackend must be ``@runtime_checkable`` so isinstance works."""
        assert getattr(StorageBackend, "_is_runtime_protocol", False) is True

    def test_protocol_inherits_per_domain_protocols(self) -> None:
        """StorageBackend must compose the per-domain Protocols via MRO."""
        from seerflow.storage.protocols import (
            AlertStore,
            EntityStore,
            LogStore,
            ModelStore,
        )

        mro = StorageBackend.__mro__
        for base in (LogStore, AlertStore, ModelStore, EntityStore):
            assert base in mro, f"StorageBackend MRO missing {base.__name__}"

    def test_protocol_advertises_composite_methods(self) -> None:
        """Sanity check the composite covers every method real call sites use."""
        required = {
            # LogStore
            "write_events",
            "query_events",
            "search_text",
            "prune_templates",
            "reset_templates",
            "flush",
            # AlertStore
            "write_alert",
            "query_alerts",
            "update_feedback",
            "get_alert_by_id",
            "get_feedback_stats",
            "count_by_severity",
            # ModelStore
            "save_state",
            "load_state",
            "delete_state",
            # EntityStore
            "get_timeline",
            "get_related",
            "set_entity_graph",
            # GraphStore subset both backends implement
            "write_edge",
            "load_edges",
            # Composite-only (lifecycle + template catalog)
            "close",
            "write_templates",
            "get_templates",
        }
        missing = required - set(dir(StorageBackend))
        assert missing == set(), f"StorageBackend missing methods: {missing}"

    async def test_sqlite_backend_satisfies_protocol(self, tmp_path: Path) -> None:
        """Connected SqliteBackend must pass ``isinstance(StorageBackend)``."""
        cfg = StorageConfig(backend="sqlite", data_dir=str(tmp_path))
        storage = await connect_storage(cfg)
        try:
            assert isinstance(storage, StorageBackend)
            # Dual compatibility: concrete type still recognisable.
            assert isinstance(storage, SqliteBackend)
        finally:
            await storage.close()
