"""Tests for YAML config loader with env var interpolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from seerflow.config import (
    ConfigError,
    SeerflowConfig,
    WebhookEndpointConfig,
    _build_correlation,
    _build_detection,
    load_config,
)


class TestDefaultConfig:
    def test_no_file_returns_defaults(self, tmp_path: Path) -> None:
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
        assert config.storage.backend == "sqlite"
        assert config.storage.postgresql_url == ""
        assert config.receivers.syslog_enabled is True
        assert config.receivers.otlp_grpc_enabled is True
        assert config.receivers.otlp_http_enabled is True
        assert config.receivers.file_paths == ()
        assert config.detection.dspot_calibration_window == 1000
        assert config.detection.dspot_risk_level == 0.0001
        assert config.detection.weights_content == 0.30
        assert config.alerting.dedup_window_seconds == 900
        assert config.alerting.webhooks == ()
        assert config.llm.backend == ""
        assert config.llm.ollama_url == "http://localhost:11434"

    def test_data_dir_uses_xdg(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SEERFLOW_DATA_DIR", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        config = load_config(None, search_dir=tmp_path)
        expected = str(Path.home() / ".local" / "share" / "seerflow")
        assert config.storage.data_dir == expected

    def test_data_dir_respects_xdg_data_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SEERFLOW_DATA_DIR", raising=False)
        monkeypatch.setenv("XDG_DATA_HOME", "/custom/xdg")
        config = load_config(None, search_dir=tmp_path)
        assert config.storage.data_dir == "/custom/xdg/seerflow"


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

    def test_env_var_set_to_empty_uses_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """${VAR:-default} with VAR="" returns "" (not default) per shell semantics."""
        monkeypatch.setenv("EMPTY_VAR", "")
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("llm:\n  backend: ${EMPTY_VAR:-llamacpp}\n")
        config = load_config(str(yaml_file))
        assert config.llm.backend == ""

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
            'receivers:\n  file_paths:\n    - "/var/log/*.log"\n    - "/home/user/test.log"\n'
        )
        config = load_config(str(yaml_file))
        assert config.receivers.file_paths == ("/var/log/*.log", "/home/user/test.log")
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
            "llm:\n  backend: ollama\n  model_path: /models/phi4.gguf\n  ollama_url: http://gpu:11434\n"
        )
        config = load_config(str(yaml_file))
        assert config.llm.backend == "ollama"
        assert config.llm.model_path == "/models/phi4.gguf"
        assert config.llm.ollama_url == "http://gpu:11434"

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


class TestConfigValidation:
    def test_nonexistent_explicit_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="Config file not found"):
            load_config(str(tmp_path / "nonexistent.yaml"))

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("key: : invalid:\n  - [broken")
        with pytest.raises(ConfigError, match="Failed to parse"):
            load_config(str(yaml_file))

    def test_invalid_log_level_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("log_level: VERBOSE\n")
        with pytest.raises(ConfigError, match="Invalid log_level"):
            load_config(str(yaml_file))

    def test_invalid_storage_backend_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("storage:\n  backend: redis\n")
        with pytest.raises(ConfigError, match=r"Invalid storage\.backend"):
            load_config(str(yaml_file))

    def test_invalid_port_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("receivers:\n  syslog_udp_port: 99999\n")
        with pytest.raises(ConfigError, match="must be between 1 and 65535"):
            load_config(str(yaml_file))

    def test_negative_port_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("dashboard_port: -1\n")
        with pytest.raises(ConfigError, match="must be between 1 and 65535"):
            load_config(str(yaml_file))


class TestWebhookConfig:
    def test_webhook_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "receivers:\n"
            "  webhooks:\n"
            "    - path: /ingest/github\n"
            "      auth_header: X-Hub-Sig\n"
            "      auth_token: secret123\n"
            "      source_id: github\n"
            "      field_mapping:\n"
            "        message: action\n"
            "        repo: repository.name\n"
        )
        cfg = load_config(str(yaml_file))
        assert len(cfg.receivers.webhooks) == 1
        wh = cfg.receivers.webhooks[0]
        assert wh.path == "/ingest/github"
        assert wh.auth_header == "X-Hub-Sig"
        assert wh.auth_token == "secret123"
        assert wh.source_id == "github"
        assert wh.field_mapping == {"message": "action", "repo": "repository.name"}

    def test_multiple_webhooks(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "receivers:\n"
            "  webhooks:\n"
            "    - path: /ingest/a\n"
            "      source_id: a\n"
            "    - path: /ingest/b\n"
            "      source_id: b\n"
        )
        cfg = load_config(str(yaml_file))
        assert len(cfg.receivers.webhooks) == 2
        assert cfg.receivers.webhooks[0].source_id == "a"
        assert cfg.receivers.webhooks[1].source_id == "b"

    def test_no_webhooks_default_empty(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("receivers:\n  syslog_enabled: true\n")
        cfg = load_config(str(yaml_file))
        assert cfg.receivers.webhooks == ()

    def test_half_auth_raises(self) -> None:
        with pytest.raises(ConfigError, match="auth_header and auth_token"):
            WebhookEndpointConfig(auth_header="X-Token")

    def test_webhook_env_var_interpolation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WH_SECRET", "env-secret")
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "receivers:\n"
            "  webhooks:\n"
            "    - path: /hook\n"
            "      auth_header: X-Secret\n"
            "      auth_token: ${WH_SECRET}\n"
        )
        cfg = load_config(str(yaml_file))
        assert cfg.receivers.webhooks[0].auth_token == "env-secret"


class TestReceiverConfigCompleteness:
    def test_defaults_match_hardcoded(self, tmp_path: Path) -> None:
        cfg = load_config(None, search_dir=tmp_path)
        r = cfg.receivers
        assert r.bind_addr == "0.0.0.0"  # noqa: S104
        assert r.queue_maxsize == 10_000
        assert r.webhook_enabled is False
        assert r.webhook_port == 8081
        assert r.file_checkpoint_dir == ""
        assert r.file_debounce_ms == 1600
        assert r.syslog_tcp_enabled is True
        assert r.otlp_http_max_request_bytes == 4_194_304
        assert r.otlp_grpc_max_workers == 4

    def test_override_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "receivers:\n"
            "  bind_addr: 127.0.0.1\n"
            "  queue_maxsize: 5000\n"
            "  webhook_enabled: true\n"
            "  webhook_port: 9090\n"
            "  file_checkpoint_dir: /tmp/checkpoints\n"
            "  file_debounce_ms: 500\n"
            "  syslog_tcp_enabled: false\n"
            "  otlp_http_max_request_bytes: 1048576\n"
            "  otlp_grpc_max_workers: 8\n"
        )
        cfg = load_config(str(yaml_file))
        r = cfg.receivers
        assert r.bind_addr == "127.0.0.1"
        assert r.queue_maxsize == 5000
        assert r.webhook_enabled is True
        assert r.webhook_port == 9090
        assert r.file_checkpoint_dir == "/tmp/checkpoints"
        assert r.file_debounce_ms == 500
        assert r.syslog_tcp_enabled is False
        assert r.otlp_http_max_request_bytes == 1_048_576
        assert r.otlp_grpc_max_workers == 8

    def test_webhook_port_validated(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("receivers:\n  webhook_port: 99999\n")
        with pytest.raises(ConfigError, match="must be between 1 and 65535"):
            load_config(str(yaml_file))

    def test_invalid_queue_maxsize_zero(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("receivers:\n  queue_maxsize: 0\n")
        with pytest.raises(ConfigError, match="queue_maxsize"):
            load_config(str(yaml_file))

    def test_invalid_otlp_http_max_request_bytes_zero(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("receivers:\n  otlp_http_max_request_bytes: 0\n")
        with pytest.raises(ConfigError, match="otlp_http_max_request_bytes"):
            load_config(str(yaml_file))

    def test_file_paths_coerced_to_strings(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("receivers:\n  file_paths:\n    - /var/log/app.log\n    - 12345\n")
        cfg = load_config(str(yaml_file))
        assert all(isinstance(p, str) for p in cfg.receivers.file_paths)
        assert cfg.receivers.file_paths[1] == "12345"

    def test_allowed_log_roots_coerced_to_strings(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("receivers:\n  allowed_log_roots:\n    - /var/log\n    - 9999\n")
        cfg = load_config(str(yaml_file))
        assert all(isinstance(r, str) for r in cfg.receivers.allowed_log_roots)
        assert cfg.receivers.allowed_log_roots[1] == "9999"

    def test_invalid_queue_maxsize_negative(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("receivers:\n  queue_maxsize: -5\n")
        with pytest.raises(ConfigError, match="queue_maxsize"):
            load_config(str(yaml_file))

    def test_invalid_otlp_http_max_request_bytes_negative(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("receivers:\n  otlp_http_max_request_bytes: -1\n")
        with pytest.raises(ConfigError, match="otlp_http_max_request_bytes"):
            load_config(str(yaml_file))


class TestDetectionValidation:
    def test_invalid_weight_negative(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"weights_content": -0.5})

    def test_invalid_weight_nan(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"weights_content": float("nan")})

    def test_invalid_weight_inf(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"weights_volume": float("inf")})

    def test_invalid_model_save_interval(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"model_save_interval_seconds": 0})

    def test_invalid_model_save_interval_negative(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"model_save_interval_seconds": -1})

    def test_invalid_markov_max_entities_too_high(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"markov_max_entities": 200_000})

    def test_invalid_markov_max_entities_zero(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"markov_max_entities": 0})

    def test_invalid_max_sources_zero(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"max_sources": 0})

    def test_invalid_max_sources_too_high(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"max_sources": 20_000})

    def test_invalid_cusum_ema_alpha_zero(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"cusum_ema_alpha": 0.0})

    def test_invalid_cusum_ema_alpha_one(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"cusum_ema_alpha": 1.0})

    def test_invalid_cusum_warmup_buckets_zero(self) -> None:
        with pytest.raises(ConfigError):
            _build_detection({"cusum_warmup_buckets": 0})

    def test_nested_hw_config(self) -> None:
        config = _build_detection({"hw": {"seasonal_period": 720, "alpha": 0.5}})
        assert config.hw_seasonal_period == 720
        assert config.hw_alpha == 0.5

    def test_flat_hw_config_backward_compat(self) -> None:
        config = _build_detection({"hw_seasonal_period": 720})
        assert config.hw_seasonal_period == 720

    def test_nested_hw_takes_priority_over_flat(self) -> None:
        config = _build_detection({"hw": {"seasonal_period": 720}, "hw_seasonal_period": 999})
        assert config.hw_seasonal_period == 720

    def test_nested_cusum_config(self) -> None:
        config = _build_detection(
            {"cusum": {"drift": 1.0, "ema_alpha": 0.2, "warmup_buckets": 10}}
        )
        assert config.cusum_drift == 1.0
        assert config.cusum_ema_alpha == 0.2
        assert config.cusum_warmup_buckets == 10

    def test_flat_cusum_config_backward_compat(self) -> None:
        config = _build_detection({"cusum_drift": 2.0, "cusum_threshold": 8.0})
        assert config.cusum_drift == 2.0
        assert config.cusum_threshold == 8.0

    def test_nested_markov_config(self) -> None:
        config = _build_detection({"markov": {"max_entities": 500, "min_events": 50}})
        assert config.markov_max_entities == 500
        assert config.markov_min_events == 50

    def test_flat_markov_config_backward_compat(self) -> None:
        config = _build_detection({"markov_max_entities": 2000})
        assert config.markov_max_entities == 2000

    def test_invalid_cusum_drift_zero(self) -> None:
        with pytest.raises(ConfigError, match="cusum_drift"):
            _build_detection({"cusum": {"drift": 0.0}})

    def test_invalid_cusum_drift_negative(self) -> None:
        with pytest.raises(ConfigError, match="cusum_drift"):
            _build_detection({"cusum": {"drift": -1.0}})

    def test_invalid_cusum_threshold_zero(self) -> None:
        with pytest.raises(ConfigError, match="cusum_threshold"):
            _build_detection({"cusum": {"threshold": 0.0}})

    def test_invalid_cusum_threshold_negative(self) -> None:
        with pytest.raises(ConfigError, match="cusum_threshold"):
            _build_detection({"cusum": {"threshold": -5.0}})

    def test_invalid_hw_alpha_zero(self) -> None:
        with pytest.raises(ConfigError, match="hw_alpha"):
            _build_detection({"hw": {"alpha": 0.0}})

    def test_invalid_hw_alpha_one(self) -> None:
        with pytest.raises(ConfigError, match="hw_alpha"):
            _build_detection({"hw": {"alpha": 1.0}})

    def test_invalid_hw_beta_negative(self) -> None:
        with pytest.raises(ConfigError, match="hw_beta"):
            _build_detection({"hw": {"beta": -0.1}})

    def test_invalid_hw_beta_zero(self) -> None:
        with pytest.raises(ConfigError, match="hw_beta"):
            _build_detection({"hw": {"beta": 0.0}})

    def test_invalid_hw_gamma_over_one(self) -> None:
        with pytest.raises(ConfigError, match="hw_gamma"):
            _build_detection({"hw": {"gamma": 1.5}})

    def test_invalid_hw_gamma_zero(self) -> None:
        with pytest.raises(ConfigError, match="hw_gamma"):
            _build_detection({"hw": {"gamma": 0.0}})

    def test_invalid_hw_n_std_zero(self) -> None:
        with pytest.raises(ConfigError, match="hw_n_std"):
            _build_detection({"hw": {"n_std": 0.0}})

    def test_invalid_hw_n_std_negative(self) -> None:
        with pytest.raises(ConfigError, match="hw_n_std"):
            _build_detection({"hw": {"n_std": -1.0}})

    def test_invalid_hw_seasonal_period_one(self) -> None:
        with pytest.raises(ConfigError, match="hw_seasonal_period"):
            _build_detection({"hw": {"seasonal_period": 1}})

    def test_invalid_cusum_drift_nan(self) -> None:
        with pytest.raises(ConfigError, match="cusum_drift"):
            _build_detection({"cusum": {"drift": float("nan")}})

    def test_invalid_cusum_threshold_inf(self) -> None:
        with pytest.raises(ConfigError, match="cusum_threshold"):
            _build_detection({"cusum": {"threshold": float("inf")}})

    def test_invalid_hw_n_std_inf(self) -> None:
        with pytest.raises(ConfigError, match="hw_n_std"):
            _build_detection({"hw": {"n_std": float("inf")}})

    def test_invalid_markov_smoothing_zero(self) -> None:
        with pytest.raises(ConfigError, match="markov_smoothing"):
            _build_detection({"markov": {"smoothing": 0.0}})

    def test_invalid_markov_smoothing_negative(self) -> None:
        with pytest.raises(ConfigError, match="markov_smoothing"):
            _build_detection({"markov": {"smoothing": -1e-6}})

    def test_invalid_markov_smoothing_inf(self) -> None:
        with pytest.raises(ConfigError, match="markov_smoothing"):
            _build_detection({"markov": {"smoothing": float("inf")}})

    def test_graph_algo_interval_default(self) -> None:
        config = SeerflowConfig()
        assert config.detection.graph_algo_interval == 500

    def test_graph_algo_interval_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="graph_algo_interval"):
            _build_detection({"graph_algo_interval": 0})

    def test_graph_algo_interval_below_minimum_raises(self) -> None:
        with pytest.raises(ConfigError, match="graph_algo_interval"):
            _build_detection({"graph_algo_interval": 9})

    def test_graph_algo_interval_above_maximum_raises(self) -> None:
        with pytest.raises(ConfigError, match="graph_algo_interval"):
            _build_detection({"graph_algo_interval": 100_001})

    def test_graph_algo_interval_at_minimum_boundary_valid(self) -> None:
        config = _build_detection({"graph_algo_interval": 10})
        assert config.graph_algo_interval == 10

    def test_graph_algo_interval_at_maximum_boundary_valid(self) -> None:
        config = _build_detection({"graph_algo_interval": 100_000})
        assert config.graph_algo_interval == 100_000

    def test_defaults_are_valid(self) -> None:
        config = _build_detection({})
        assert config.hw_seasonal_period == 1440
        assert config.cusum_ema_alpha == 0.1
        assert config.cusum_warmup_buckets == 30
        assert config.weights_content == 0.30


class TestSigmaRulesDirsConfig:
    def test_default_is_empty_tuple(self) -> None:
        config = _build_detection({})
        assert config.sigma_rules_dirs == ()

    def test_sigma_rules_dirs_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "detection:\n  sigma_rules_dirs:\n    - /etc/seerflow/rules\n    - /opt/rules\n"
        )
        cfg = load_config(str(yaml_file))
        assert cfg.detection.sigma_rules_dirs == ("/etc/seerflow/rules", "/opt/rules")

    def test_sigma_rules_dirs_coerced_to_strings(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("detection:\n  sigma_rules_dirs:\n    - /path/one\n    - 12345\n")
        cfg = load_config(str(yaml_file))
        assert cfg.detection.sigma_rules_dirs == ("/path/one", "12345")

    def test_sigma_rules_dirs_scalar_raises_config_error(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("detection:\n  sigma_rules_dirs: /etc/rules\n")
        with pytest.raises(ConfigError, match="sigma_rules_dirs must be a list"):
            load_config(str(yaml_file))


class TestCorrelationConfig:
    def test_default_window_duration(self) -> None:
        config = SeerflowConfig()
        assert config.correlation.window_duration_seconds == 1800  # 30 min

    def test_default_max_events_per_entity(self) -> None:
        config = SeerflowConfig()
        assert config.correlation.max_events_per_entity == 1000

    def test_default_max_entities(self) -> None:
        config = SeerflowConfig()
        assert config.correlation.max_entities == 10_000

    def test_build_correlation_defaults(self) -> None:
        config = _build_correlation({})
        assert config.window_duration_seconds == 1800
        assert config.max_events_per_entity == 1000
        assert config.max_entities == 10_000

    def test_build_correlation_custom_values(self) -> None:
        config = _build_correlation(
            {
                "window_duration_seconds": 3600,
                "max_events_per_entity": 500,
                "max_entities": 5000,
            }
        )
        assert config.window_duration_seconds == 3600
        assert config.max_events_per_entity == 500
        assert config.max_entities == 5000

    def test_correlation_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "correlation:\n"
            "  window_duration_seconds: 900\n"
            "  max_events_per_entity: 2000\n"
            "  max_entities: 20000\n"
        )
        config = load_config(str(yaml_file))
        assert config.correlation.window_duration_seconds == 900
        assert config.correlation.max_events_per_entity == 2000
        assert config.correlation.max_entities == 20_000

    def test_correlation_config_is_frozen(self) -> None:
        config = SeerflowConfig()
        with pytest.raises(AttributeError):
            config.correlation.window_duration_seconds = 999  # type: ignore[misc]
