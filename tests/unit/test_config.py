"""Tests for YAML config loader with env var interpolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from seerflow.config import ConfigError, SeerflowConfig, load_config


class TestDefaultConfig:
    def test_no_file_returns_defaults(self, tmp_path: Path) -> None:
        """load_config with no file in a clean dir returns all defaults."""
        config = load_config(None, search_dir=tmp_path)
        assert isinstance(config, SeerflowConfig)
        assert config.storage.backend == "sqlite"
        assert config.receivers.syslog_udp_port == 514
        assert config.receivers.otlp_grpc_port == 4317
        assert config.receivers.otlp_http_port == 4318
        assert config.dashboard_port == 8080
        assert config.log_level == "INFO"

    def test_default_section_values(self, tmp_path: Path) -> None:
        config = load_config(None, search_dir=tmp_path)
        # Storage
        assert config.storage.backend == "sqlite"
        assert config.storage.postgresql_url == ""
        # Receivers
        assert config.receivers.syslog_enabled is True
        assert config.receivers.otlp_grpc_enabled is True
        assert config.receivers.otlp_http_enabled is True
        assert config.receivers.file_paths == ()
        # Detection
        assert config.detection.dspot_calibration_window == 1000
        assert config.detection.dspot_risk_level == 0.0001
        assert config.detection.weights_content == 0.30
        # Alerting
        assert config.alerting.dedup_window_seconds == 900
        assert config.alerting.webhooks == ()
        # LLM
        assert config.llm.backend == ""
        assert config.llm.ollama_url == "http://localhost:11434"

    def test_data_dir_uses_xdg(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SEERFLOW_DATA_DIR", raising=False)
        config = load_config(None, search_dir=tmp_path)
        expected = str(Path.home() / ".local" / "share" / "seerflow")
        assert config.storage.data_dir == expected


class TestEnvVarInterpolation:
    def test_env_var_substitution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_SEERFLOW_BACKEND", "postgresql")
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("storage:\n  backend: ${TEST_SEERFLOW_BACKEND}\n")
        config = load_config(str(yaml_file))
        assert config.storage.backend == "postgresql"

    def test_env_var_with_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNSET_VAR_12345", raising=False)
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("storage:\n  backend: ${UNSET_VAR_12345:-sqlite}\n")
        config = load_config(str(yaml_file))
        assert config.storage.backend == "sqlite"

    def test_missing_env_var_no_default_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MISSING_REQUIRED_VAR", raising=False)
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("storage:\n  postgresql_url: ${MISSING_REQUIRED_VAR}\n")
        with pytest.raises(ConfigError, match="MISSING_REQUIRED_VAR"):
            load_config(str(yaml_file))

    def test_env_var_embedded_in_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB_PASS", "s3cret")
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "storage:\n  postgresql_url: postgresql://${DB_USER:-seer}:${DB_PASS}@localhost/db\n"
        )
        config = load_config(str(yaml_file))
        assert config.storage.postgresql_url == "postgresql://seer:s3cret@localhost/db"


class TestPartialConfig:
    def test_partial_merge_preserves_defaults(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("storage:\n  backend: postgresql\n")
        config = load_config(str(yaml_file))
        assert config.storage.backend == "postgresql"
        # Other sections should be defaults
        assert config.receivers.syslog_udp_port == 514
        assert config.detection.dspot_calibration_window == 1000
        assert config.dashboard_port == 8080


class TestConfigLoading:
    def test_load_from_explicit_path(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "custom.yaml"
        yaml_file.write_text("dashboard_port: 9090\n")
        config = load_config(str(yaml_file))
        assert config.dashboard_port == 9090

    def test_yaml_lists_become_tuples(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            'receivers:\n  file_paths:\n    - "/var/log/*.log"\n    - "/tmp/test.log"\n'
        )
        config = load_config(str(yaml_file))
        assert config.receivers.file_paths == ("/var/log/*.log", "/tmp/test.log")  # noqa: S108
        assert isinstance(config.receivers.file_paths, tuple)

    def test_config_is_frozen(self, tmp_path: Path) -> None:
        config = load_config(None, search_dir=tmp_path)
        with pytest.raises(AttributeError):
            config.dashboard_port = 9999  # type: ignore[misc]
        with pytest.raises(AttributeError):
            config.storage.backend = "nope"  # type: ignore[misc]

    def test_data_dir_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEERFLOW_DATA_DIR", "/custom/data")
        config = load_config(None, search_dir=tmp_path)
        assert config.storage.data_dir == "/custom/data"

    def test_webhooks_list_becomes_tuple(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "alerting:\n  webhooks:\n    - url: https://hooks.slack.com/xxx\n      format: slack\n"
        )
        config = load_config(str(yaml_file))
        assert isinstance(config.alerting.webhooks, tuple)
        assert len(config.alerting.webhooks) == 1
        assert config.alerting.webhooks[0]["format"] == "slack"

    def test_llm_config(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "llm:\n"
            "  backend: ollama\n"
            "  model_path: /models/phi4.gguf\n"
            "  ollama_url: http://gpu-server:11434\n"
        )
        config = load_config(str(yaml_file))
        assert config.llm.backend == "ollama"
        assert config.llm.model_path == "/models/phi4.gguf"
        assert config.llm.ollama_url == "http://gpu-server:11434"

    def test_detection_dspot_nested(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "detection:\n  dspot:\n    calibration_window: 2000\n    risk_level: 0.001\n"
        )
        config = load_config(str(yaml_file))
        assert config.detection.dspot_calibration_window == 2000
        assert config.detection.dspot_risk_level == 0.001

    def test_cwd_auto_discovery(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("log_level: DEBUG\n")
        config = load_config(None, search_dir=tmp_path)
        assert config.log_level == "DEBUG"

    def test_nonexistent_explicit_path(self, tmp_path: Path) -> None:
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        assert config.dashboard_port == 8080  # defaults
