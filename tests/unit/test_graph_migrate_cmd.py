"""Unit tests for ``seerflow graph migrate`` handler (S-155-F3).

The handler is exercised end-to-end via two real ``InMemoryIgraphBackend``
instances — no mocks needed for the orchestration path. The factory is
patched to dispatch on the synthetic ``graph_backend`` value, returning
the right pre-populated backend for each side.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from seerflow.config import SeerflowConfig, StorageConfig
from seerflow.graph.backends import InMemoryIgraphBackend
from seerflow.graph_migrate_cmd import run_graph_migrate

if TYPE_CHECKING:
    from collections.abc import Iterator


_SAMPLE_EDGES: list[tuple[str, str, str, int, int, int]] = [
    ("alice", "host-1", "logged_in_to", 100, 500, 3),
    ("alice", "host-2", "logged_in_to", 110, 510, 2),
    ("bob", "host-1", "logged_in_to", 120, 520, 1),
    ("bob", "host-3", "ssh_failed", 130, 530, 7),
    ("carol", "host-2", "sudo_ran", 140, 540, 4),
    ("carol", "10.0.0.1", "connected_from", 150, 550, 9),
    ("dave", "host-4", "logged_in_to", 160, 560, 1),
    ("eve", "host-5", "logged_in_to", 170, 570, 5),
    ("eve", "host-1", "scp_to", 180, 580, 2),
    ("frank", "host-6", "logged_in_to", 190, 590, 1),
]
"""Ten representative edges. ``add_edge`` collisions exercised below."""


def _populate(
    backend: InMemoryIgraphBackend,
    edges: list[tuple[str, str, str, int, int, int]],
) -> None:
    """Seed ``backend`` with the given edge tuples via the public ``load`` API."""
    backend.inner_graph.load(edges)


def _make_args(
    *,
    from_backend: str = "igraph",
    to_backend: str = "falkordb",
    batch_size: int = 5000,
    dry_run: bool = False,
    wipe_destination: bool = False,
    config: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        command="graph",
        graph_cmd="migrate",
        from_backend=from_backend,
        to_backend=to_backend,
        batch_size=batch_size,
        dry_run=dry_run,
        wipe_destination=wipe_destination,
        config=config,
    )


@pytest.fixture
def patched_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, InMemoryIgraphBackend]]:
    """Patch ``connect_graph`` and ``load_config`` to return canned backends.

    Yields a dict keyed by the synthetic ``graph_backend`` value. Tests
    pre-populate the entries before calling ``run_graph_migrate``.
    """
    registry: dict[str, InMemoryIgraphBackend] = {
        "igraph": InMemoryIgraphBackend(),
        "falkordb": InMemoryIgraphBackend(),
        "postgres_age": InMemoryIgraphBackend(),
    }

    async def fake_connect(storage_cfg: StorageConfig) -> InMemoryIgraphBackend:
        return registry[storage_cfg.graph_backend]

    def fake_load_config(path: str | None) -> SeerflowConfig:
        return SeerflowConfig(
            storage=StorageConfig(
                backend="sqlite",
                graph_backend="igraph",  # base value; the handler swaps it per side
                falkordb_url="redis://fake/0",
                postgresql_url="postgresql://fake/db",
            ),
        )

    monkeypatch.setattr("seerflow.graph_migrate_cmd.connect_graph", fake_connect)
    monkeypatch.setattr("seerflow.graph_migrate_cmd.load_config", fake_load_config)
    yield registry


@pytest.mark.asyncio
class TestRunGraphMigrate:
    async def test_happy_path_in_memory_round_trip(
        self,
        patched_factory: dict[str, InMemoryIgraphBackend],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)
        # destination starts empty

        rc = await run_graph_migrate(_make_args(from_backend="igraph", to_backend="falkordb"))

        assert rc == 0
        dest_edges = await patched_factory["falkordb"].export_edges()
        assert len(dest_edges) == len(_SAMPLE_EDGES)
        # Same set of (src, tgt, rel) tuples on both sides — semantics preserved.
        assert {(e[0], e[1], e[2]) for e in dest_edges} == {
            (e[0], e[1], e[2]) for e in _SAMPLE_EDGES
        }
        captured = capsys.readouterr()
        assert "migrated" in captured.out.lower()
        assert "edges" in captured.out.lower()

    async def test_dry_run_does_not_touch_destination(
        self,
        patched_factory: dict[str, InMemoryIgraphBackend],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)

        rc = await run_graph_migrate(
            _make_args(from_backend="igraph", to_backend="falkordb", dry_run=True),
        )

        assert rc == 0
        # Destination must remain empty in dry-run mode.
        dest_edges = await patched_factory["falkordb"].export_edges()
        assert dest_edges == []
        captured = capsys.readouterr()
        out_lower = captured.out.lower()
        assert "dry-run" in out_lower or "dry run" in out_lower
        assert str(len(_SAMPLE_EDGES)) in captured.out

    async def test_same_source_and_destination_rejected(
        self,
        patched_factory: dict[str, InMemoryIgraphBackend],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = await run_graph_migrate(_make_args(from_backend="igraph", to_backend="igraph"))
        assert rc == 1
        # No backend should have been mutated.
        for backend in patched_factory.values():
            assert (await backend.export_edges()) == []
        captured = capsys.readouterr()
        assert "must differ" in captured.err.lower() or "same" in captured.err.lower()

    async def test_empty_source_succeeds(
        self,
        patched_factory: dict[str, InMemoryIgraphBackend],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # source stays empty
        rc = await run_graph_migrate(_make_args(from_backend="igraph", to_backend="falkordb"))
        assert rc == 0
        captured = capsys.readouterr()
        assert "0 edges" in captured.out

    async def test_batch_size_smaller_than_total_multiple_chunks(
        self,
        patched_factory: dict[str, InMemoryIgraphBackend],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)

        rc = await run_graph_migrate(
            _make_args(from_backend="igraph", to_backend="falkordb", batch_size=3),
        )

        assert rc == 0
        dest_edges = await patched_factory["falkordb"].export_edges()
        assert len(dest_edges) == len(_SAMPLE_EDGES)
        # Progress lines on stderr should mention multiple batches.
        captured = capsys.readouterr()
        # 10 edges in batches of 3 → 4 progress lines (3, 6, 9, 10).
        progress_lines = [line for line in captured.err.splitlines() if "migrated" in line.lower()]
        assert len(progress_lines) >= 2

    async def test_batch_size_equal_to_total_single_chunk(
        self,
        patched_factory: dict[str, InMemoryIgraphBackend],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)
        rc = await run_graph_migrate(
            _make_args(
                from_backend="igraph",
                to_backend="falkordb",
                batch_size=len(_SAMPLE_EDGES),
            ),
        )
        assert rc == 0
        assert (await patched_factory["falkordb"].export_edges()).__len__() == len(_SAMPLE_EDGES)

    async def test_batch_size_larger_than_total_single_chunk(
        self,
        patched_factory: dict[str, InMemoryIgraphBackend],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)
        rc = await run_graph_migrate(
            _make_args(
                from_backend="igraph",
                to_backend="falkordb",
                batch_size=10_000,
            ),
        )
        assert rc == 0
        assert (await patched_factory["falkordb"].export_edges()).__len__() == len(_SAMPLE_EDGES)

    async def test_wipe_destination_empties_before_streaming(
        self,
        patched_factory: dict[str, InMemoryIgraphBackend],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)
        # Pre-populate destination with stale edges that must be wiped.
        stale = [("stale", "garbage", "rel_old", 1, 2, 1)]
        _populate(patched_factory["falkordb"], stale)

        rc = await run_graph_migrate(
            _make_args(
                from_backend="igraph",
                to_backend="falkordb",
                wipe_destination=True,
            ),
        )

        assert rc == 0
        dest_edges = await patched_factory["falkordb"].export_edges()
        # Stale edge must be gone.
        assert ("stale", "garbage") not in {(e[0], e[1]) for e in dest_edges}
        # All source edges present.
        assert {(e[0], e[1], e[2]) for e in dest_edges} == {
            (e[0], e[1], e[2]) for e in _SAMPLE_EDGES
        }

    async def test_re_running_is_idempotent(
        self,
        patched_factory: dict[str, InMemoryIgraphBackend],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)

        rc1 = await run_graph_migrate(_make_args(from_backend="igraph", to_backend="falkordb"))
        first = await patched_factory["falkordb"].export_edges()

        rc2 = await run_graph_migrate(_make_args(from_backend="igraph", to_backend="falkordb"))
        second = await patched_factory["falkordb"].export_edges()

        assert rc1 == 0
        assert rc2 == 0
        # Re-running adds no new edges (every backend MERGEs on src/tgt/rel).
        assert {(e[0], e[1], e[2]) for e in first} == {(e[0], e[1], e[2]) for e in second}

    async def test_verification_mismatch_returns_nonzero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_factory: dict[str, InMemoryIgraphBackend],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)

        class NoOpAddBackend:
            def __init__(self, inner: InMemoryIgraphBackend) -> None:
                self._inner = inner

            def __getattr__(self, name: str) -> object:
                return getattr(self._inner, name)

            async def add_edge(self, *_args: object, **_kw: object) -> None:
                # Never writes — the destination stays empty, forcing the
                # post-migration count check to fail.
                return None

            @property
            def vertex_count(self) -> int:
                return self._inner.vertex_count

            @property
            def edge_count(self) -> int:
                return self._inner.edge_count

        async def broken_dest_connect(storage_cfg: StorageConfig) -> object:
            if storage_cfg.graph_backend == "falkordb":
                return NoOpAddBackend(patched_factory["falkordb"])
            return patched_factory[storage_cfg.graph_backend]

        monkeypatch.setattr("seerflow.graph_migrate_cmd.connect_graph", broken_dest_connect)

        rc = await run_graph_migrate(_make_args(from_backend="igraph", to_backend="falkordb"))
        assert rc == 2
        captured = capsys.readouterr()
        assert "verification" in captured.err.lower() or "mismatch" in captured.err.lower()

    async def test_dry_run_does_not_connect_destination(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_factory: dict[str, InMemoryIgraphBackend],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)
        connect_calls: list[str] = []

        original_connect = patched_factory.copy()

        async def tracking_connect(storage_cfg: StorageConfig) -> InMemoryIgraphBackend:
            connect_calls.append(storage_cfg.graph_backend)
            return original_connect[storage_cfg.graph_backend]

        monkeypatch.setattr("seerflow.graph_migrate_cmd.connect_graph", tracking_connect)

        rc = await run_graph_migrate(
            _make_args(from_backend="igraph", to_backend="falkordb", dry_run=True),
        )
        assert rc == 0
        # Only the source was connected.
        assert connect_calls == ["igraph"]

    async def test_close_called_when_backend_supports_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_factory: dict[str, InMemoryIgraphBackend],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)
        close_calls: list[str] = []

        class WrappedBackend:
            def __init__(self, inner: InMemoryIgraphBackend, label: str) -> None:
                self._inner = inner
                self._label = label

            def __getattr__(self, name: str) -> object:
                return getattr(self._inner, name)

            async def close(self) -> None:
                close_calls.append(self._label)

            @property
            def vertex_count(self) -> int:
                return self._inner.vertex_count

            @property
            def edge_count(self) -> int:
                return self._inner.edge_count

        async def closeable_connect(storage_cfg: StorageConfig) -> object:
            return WrappedBackend(
                patched_factory[storage_cfg.graph_backend],
                storage_cfg.graph_backend,
            )

        monkeypatch.setattr("seerflow.graph_migrate_cmd.connect_graph", closeable_connect)

        rc = await run_graph_migrate(_make_args(from_backend="igraph", to_backend="falkordb"))
        assert rc == 0
        assert set(close_calls) == {"igraph", "falkordb"}

    async def test_refresh_counts_called_when_available(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_factory: dict[str, InMemoryIgraphBackend],
    ) -> None:
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)
        refresh_calls: list[str] = []

        class RefreshableBackend:
            def __init__(self, inner: InMemoryIgraphBackend, label: str) -> None:
                self._inner = inner
                self._label = label

            def __getattr__(self, name: str) -> object:
                return getattr(self._inner, name)

            async def refresh_counts(self) -> None:
                refresh_calls.append(self._label)

            @property
            def vertex_count(self) -> int:
                return self._inner.vertex_count

            @property
            def edge_count(self) -> int:
                return self._inner.edge_count

        async def refresh_connect(storage_cfg: StorageConfig) -> object:
            return RefreshableBackend(
                patched_factory[storage_cfg.graph_backend], storage_cfg.graph_backend
            )

        monkeypatch.setattr("seerflow.graph_migrate_cmd.connect_graph", refresh_connect)

        rc = await run_graph_migrate(_make_args(from_backend="igraph", to_backend="falkordb"))
        assert rc == 0
        # Both sides refreshed before the verification step.
        assert set(refresh_calls) == {"igraph", "falkordb"}

    async def test_wipe_strict_equality_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_factory: dict[str, InMemoryIgraphBackend],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """With ``--wipe-destination`` set, mismatched counts must exit 2."""
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)
        dest_inner = patched_factory["falkordb"]

        class HalfAddBackend:
            def __init__(self, inner: InMemoryIgraphBackend) -> None:
                self._inner = inner
                self._n = 0

            def __getattr__(self, name: str) -> object:
                return getattr(self._inner, name)

            async def add_edge(self, src: str, tgt: str, rel: str, ts: int) -> None:
                self._n += 1
                if self._n % 2 == 0:
                    # Drop every other edge — destination ends up smaller than
                    # source, breaking the strict-equality check.
                    return
                await self._inner.add_edge(src, tgt, rel, ts)

            async def load(self, rows: list[tuple[str, str, str, int, int, int]]) -> None:
                await self._inner.load(rows)

            @property
            def vertex_count(self) -> int:
                return self._inner.vertex_count

            @property
            def edge_count(self) -> int:
                return self._inner.edge_count

        async def half_connect(storage_cfg: StorageConfig) -> object:
            if storage_cfg.graph_backend == "falkordb":
                return HalfAddBackend(dest_inner)
            return patched_factory[storage_cfg.graph_backend]

        monkeypatch.setattr("seerflow.graph_migrate_cmd.connect_graph", half_connect)

        rc = await run_graph_migrate(
            _make_args(
                from_backend="igraph",
                to_backend="falkordb",
                wipe_destination=True,
            ),
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "verification" in captured.err.lower() or "mismatch" in captured.err.lower()

    async def test_config_replace_used_per_side(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_factory: dict[str, InMemoryIgraphBackend],
    ) -> None:
        """The handler must call ``connect_graph`` with the per-side override."""
        _populate(patched_factory["igraph"], _SAMPLE_EDGES)
        seen_backends: list[str] = []

        async def tracking_connect(storage_cfg: StorageConfig) -> InMemoryIgraphBackend:
            seen_backends.append(storage_cfg.graph_backend)
            return patched_factory[storage_cfg.graph_backend]

        monkeypatch.setattr("seerflow.graph_migrate_cmd.connect_graph", tracking_connect)

        rc = await run_graph_migrate(
            _make_args(from_backend="postgres_age", to_backend="falkordb"),
        )
        assert rc == 0
        assert seen_backends == ["postgres_age", "falkordb"]
        # The base config's graph_backend was "igraph"; the handler swapped it.
        # Sanity-check the synthetic config helper actually flips the field.
        base = StorageConfig(graph_backend="igraph")
        swapped = replace(base, graph_backend="postgres_age")
        assert swapped.graph_backend == "postgres_age"
        assert base.graph_backend == "igraph"  # original untouched
