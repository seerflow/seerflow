"""Unit tests for ``storage.graph_backend`` config key (S-155 Task 3)."""

from __future__ import annotations

import pytest

from seerflow._config_builders import _build_storage
from seerflow.config import ConfigError


class TestStorageGraphBackendConfig:
    def test_defaults_to_igraph_when_omitted(self) -> None:
        cfg = _build_storage({"backend": "sqlite"})
        assert cfg.graph_backend == "igraph"

    @pytest.mark.parametrize("value", ["igraph", "falkordb", "postgres_age"])
    def test_accepts_valid_values(self, value: str) -> None:
        cfg = _build_storage({"backend": "sqlite", "graph_backend": value})
        assert cfg.graph_backend == value

    def test_rejects_unknown_value_with_helpful_message(self) -> None:
        with pytest.raises(ConfigError) as exc_info:
            _build_storage({"backend": "sqlite", "graph_backend": "redis"})
        msg = str(exc_info.value)
        assert "graph_backend" in msg
        assert "'redis'" in msg or "redis" in msg
        assert "igraph" in msg

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ConfigError, match="graph_backend"):
            _build_storage({"backend": "sqlite", "graph_backend": ""})

    def test_graph_backend_independent_of_storage_backend(self) -> None:
        cfg = _build_storage(
            {
                "backend": "postgresql",
                "postgresql_url": "postgresql://localhost/seerflow",
                "graph_backend": "igraph",
            }
        )
        assert cfg.backend == "postgresql"
        assert cfg.graph_backend == "igraph"
