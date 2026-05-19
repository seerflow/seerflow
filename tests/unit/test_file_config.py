"""Config validation for the S-313 file alert sink (AlertingConfig.file_*)."""

from __future__ import annotations

from pathlib import Path

import pytest

from seerflow._config_builders import _build_alerting
from seerflow.config import AlertingConfig, ConfigError


def test_defaults_disable_file_sink() -> None:
    c = AlertingConfig()
    assert c.file_enabled is False
    assert c.file_path == ""
    assert c.file_rotation == "size"
    assert c.file_max_bytes == 10 * 1024 * 1024
    assert c.file_backup_count == 5
    assert c.file_min_severity == 0


def test_build_alerting_file_defaults_when_absent() -> None:
    c = _build_alerting({})
    assert c.file_enabled is False
    assert c.file_path == ""


def test_valid_path_enables_file_sink(tmp_path: Path) -> None:
    target = tmp_path / "alerts.ndjson"
    c = _build_alerting({"file_path": str(target)})
    assert c.file_enabled is True
    assert c.file_path == str(target)
    assert c.file_rotation == "size"


def test_build_alerting_reads_file_block(tmp_path: Path) -> None:
    target = tmp_path / "a.ndjson"
    c = _build_alerting(
        {
            "file_path": str(target),
            "file_rotation": "time",
            "file_max_bytes": 4096,
            "file_interval_seconds": 3600,
            "file_backup_count": 9,
            "file_min_severity": 3,
        }
    )
    assert c.file_enabled is True
    assert c.file_rotation == "time"
    assert c.file_max_bytes == 4096
    assert c.file_interval_seconds == 3600
    assert c.file_backup_count == 9
    assert c.file_min_severity == 3


def test_path_is_directory_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file_path"):
        _build_alerting({"file_path": str(tmp_path)})


def test_missing_parent_dir_fails_fast(tmp_path: Path) -> None:
    bad = tmp_path / "no_such_dir" / "a.ndjson"
    with pytest.raises(ConfigError, match="file_path"):
        _build_alerting({"file_path": str(bad)})


def test_non_string_path_fails_fast() -> None:
    with pytest.raises(ConfigError, match="file_path"):
        _build_alerting({"file_path": 123})


def test_invalid_rotation_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file_rotation"):
        _build_alerting({"file_path": str(tmp_path / "a.ndjson"), "file_rotation": "weekly"})


def test_invalid_max_bytes_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file_max_bytes"):
        _build_alerting({"file_path": str(tmp_path / "a.ndjson"), "file_max_bytes": 0})


def test_invalid_interval_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file_interval_seconds"):
        _build_alerting({"file_path": str(tmp_path / "a.ndjson"), "file_interval_seconds": -1})


def test_invalid_backup_count_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file_backup_count"):
        _build_alerting({"file_path": str(tmp_path / "a.ndjson"), "file_backup_count": -2})


def test_invalid_min_severity_out_of_range_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file_min_severity"):
        _build_alerting({"file_path": str(tmp_path / "a.ndjson"), "file_min_severity": 99})


def test_invalid_min_severity_non_int_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file_min_severity"):
        _build_alerting({"file_path": str(tmp_path / "a.ndjson"), "file_min_severity": "high"})
