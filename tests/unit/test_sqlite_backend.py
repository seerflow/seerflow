"""Tests for SqliteBackend — schema creation, event batch writes."""

from __future__ import annotations

import pytest

from seerflow.config import ConfigError
from seerflow.storage.sqlite import _validate_path


class TestPathValidation:
    def test_null_byte_rejected(self) -> None:
        with pytest.raises(ConfigError, match="null byte"):
            _validate_path("/tmp/bad\x00path.db")

    def test_null_byte_in_middle(self) -> None:
        with pytest.raises(ConfigError, match="null byte"):
            _validate_path("/tmp/some\x00/dir/file.db")

    def test_valid_path_passes(self) -> None:
        _validate_path("/tmp/valid/path/seerflow.db")

    def test_empty_path_passes(self) -> None:
        _validate_path("")
