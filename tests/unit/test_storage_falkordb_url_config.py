"""Unit tests for ``StorageConfig.falkordb_url`` (S-155-F1)."""

from __future__ import annotations

import pytest

from seerflow.config import StorageConfig


@pytest.mark.unit
def test_falkordb_url_defaults_to_empty() -> None:
    cfg = StorageConfig(backend="sqlite")
    assert cfg.falkordb_url == ""


@pytest.mark.unit
def test_falkordb_url_accepts_url_form() -> None:
    cfg = StorageConfig(backend="sqlite", falkordb_url="falkor://localhost:6379")
    assert cfg.falkordb_url == "falkor://localhost:6379"


@pytest.mark.unit
def test_falkordb_url_not_in_repr() -> None:
    """``repr=False`` keeps the URL (with potential credentials) out of repr."""
    cfg = StorageConfig(
        backend="sqlite",
        falkordb_url="falkor://user:secret@host:6379",
    )
    assert "secret" not in repr(cfg)
    assert "falkordb_url" not in repr(cfg)
