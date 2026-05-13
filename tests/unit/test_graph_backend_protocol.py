"""Unit tests for the GraphBackend Protocol (S-155 Task 1)."""

from __future__ import annotations

import pytest

from seerflow.graph.backends import GraphBackend


class TestGraphBackendProtocol:
    """Confirm ``GraphBackend`` is a runtime-checkable Protocol."""

    def test_protocol_rejects_unrelated_class(self) -> None:
        class _Empty:
            pass

        assert not isinstance(_Empty(), GraphBackend)

    def test_protocol_accepts_minimal_async_impl(self) -> None:
        class _Minimal:
            async def add_edge(
                self,
                source_id: str,
                target_id: str,
                rel_type: str,
                timestamp_ns: int,
            ) -> None:
                return None

            async def get_neighbors(
                self,
                entity_id: str,
                *,
                rel_types: tuple[str, ...] | None = None,
                depth: int = 1,
            ) -> list[dict[str, str]]:
                return []

            async def shortest_path(self, source_id: str, target_id: str) -> list[str]:
                return []

            async def get_subgraph(
                self,
                entity_id: str,
                depth: int = 2,
            ) -> tuple[list[str], list[dict[str, str]]]:
                return ([], [])

            async def get_related(self, entity_uuid: str) -> list[object]:
                return []

            async def load(
                self,
                rows: list[tuple[str, str, str, int, int, int]],
            ) -> None:
                return None

            async def export_edges(self) -> list[tuple[str, str, str, int, int, int]]:
                return []

            @property
            def vertex_count(self) -> int:
                return 0

            @property
            def edge_count(self) -> int:
                return 0

        assert isinstance(_Minimal(), GraphBackend)

    def test_protocol_rejects_partial_impl_missing_async_method(self) -> None:
        class _Partial:
            async def add_edge(
                self,
                source_id: str,
                target_id: str,
                rel_type: str,
                timestamp_ns: int,
            ) -> None:
                return None

            @property
            def vertex_count(self) -> int:
                return 0

        assert not isinstance(_Partial(), GraphBackend)


@pytest.mark.unit
def test_graph_backend_module_exports() -> None:
    """The package re-exports the Protocol via the public ``backends`` API."""
    from seerflow.graph import backends

    assert hasattr(backends, "GraphBackend")
    assert backends.GraphBackend is GraphBackend
