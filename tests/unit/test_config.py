"""Tests for YAML config loader with env var interpolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from seerflow.config import (
    ConfigError,
    SeerflowConfig,
    StorageConfig,
    WebhookEndpointConfig,
    _build_correlation,
    _build_detection,
    _build_receivers,
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
        with pytest.raises(ConfigError, match="weights_content"):
            _build_detection({"weights_content": -0.5})

    def test_invalid_weight_nan(self) -> None:
        with pytest.raises(ConfigError, match="weights_content"):
            _build_detection({"weights_content": float("nan")})

    def test_invalid_weight_inf(self) -> None:
        with pytest.raises(ConfigError, match="weights_volume"):
            _build_detection({"weights_volume": float("inf")})

    def test_invalid_model_save_interval(self) -> None:
        with pytest.raises(ConfigError, match="model_save_interval_seconds"):
            _build_detection({"model_save_interval_seconds": 0})

    def test_invalid_model_save_interval_negative(self) -> None:
        with pytest.raises(ConfigError, match="model_save_interval_seconds"):
            _build_detection({"model_save_interval_seconds": -1})

    def test_invalid_markov_max_entities_too_high(self) -> None:
        with pytest.raises(ConfigError, match="markov_max_entities"):
            _build_detection({"markov_max_entities": 200_000})

    def test_invalid_markov_max_entities_zero(self) -> None:
        with pytest.raises(ConfigError, match="markov_max_entities"):
            _build_detection({"markov_max_entities": 0})

    def test_invalid_max_sources_zero(self) -> None:
        with pytest.raises(ConfigError, match="max_sources"):
            _build_detection({"max_sources": 0})

    def test_invalid_max_sources_too_high(self) -> None:
        with pytest.raises(ConfigError, match="max_sources"):
            _build_detection({"max_sources": 20_000})

    def test_invalid_cusum_ema_alpha_zero(self) -> None:
        with pytest.raises(ConfigError, match="cusum_ema_alpha"):
            _build_detection({"cusum_ema_alpha": 0.0})

    def test_invalid_cusum_ema_alpha_one(self) -> None:
        with pytest.raises(ConfigError, match="cusum_ema_alpha"):
            _build_detection({"cusum_ema_alpha": 1.0})

    def test_invalid_cusum_warmup_buckets_zero(self) -> None:
        with pytest.raises(ConfigError, match="cusum_warmup_buckets"):
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

    # --- S-146: Missing detection validations ---

    def test_hst_window_size_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="hst_window_size"):
            _build_detection({"hst_window_size": 0})

    def test_hst_window_size_negative_raises(self) -> None:
        with pytest.raises(ConfigError, match="hst_window_size"):
            _build_detection({"hst_window_size": -1})

    def test_hst_n_trees_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="hst_n_trees"):
            _build_detection({"hst_n_trees": 0})

    def test_dspot_calibration_window_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="dspot_calibration_window"):
            _build_detection({"dspot": {"calibration_window": 0}})

    def test_dspot_risk_level_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="dspot_risk_level"):
            _build_detection({"dspot": {"risk_level": 0.0}})

    def test_dspot_risk_level_one_raises(self) -> None:
        with pytest.raises(ConfigError, match="dspot_risk_level"):
            _build_detection({"dspot": {"risk_level": 1.0}})

    def test_dspot_risk_level_negative_raises(self) -> None:
        with pytest.raises(ConfigError, match="dspot_risk_level"):
            _build_detection({"dspot": {"risk_level": -0.1}})

    def test_dspot_initial_percentile_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="dspot_initial_percentile"):
            _build_detection({"dspot": {"initial_percentile": 0}})

    def test_dspot_initial_percentile_101_raises(self) -> None:
        with pytest.raises(ConfigError, match="dspot_initial_percentile"):
            _build_detection({"dspot": {"initial_percentile": 101}})

    def test_markov_min_events_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="markov_min_events"):
            _build_detection({"markov": {"min_events": 0}})

    def test_markov_min_events_negative_raises(self) -> None:
        with pytest.raises(ConfigError, match="markov_min_events"):
            _build_detection({"markov": {"min_events": -5}})


class TestReceiverUpperBounds:
    """S-146: Upper-bound checks to prevent OOM."""

    def test_queue_maxsize_too_large_raises(self) -> None:
        with pytest.raises(ConfigError, match="queue_maxsize"):
            _build_receivers({"queue_maxsize": 1_000_001})

    def test_otlp_http_max_request_bytes_too_large_raises(self) -> None:
        with pytest.raises(ConfigError, match="otlp_http_max_request_bytes"):
            _build_receivers({"otlp_http_max_request_bytes": 100_000_001})

    def test_queue_maxsize_at_upper_bound_valid(self) -> None:
        cfg = _build_receivers({"queue_maxsize": 1_000_000})
        assert cfg.queue_maxsize == 1_000_000

    def test_otlp_http_max_request_bytes_at_upper_bound_valid(self) -> None:
        cfg = _build_receivers({"otlp_http_max_request_bytes": 100_000_000})
        assert cfg.otlp_http_max_request_bytes == 100_000_000


class TestStorageConfigRepr:
    """S-146: postgresql_url must not leak in repr."""

    def test_postgresql_url_not_in_repr(self) -> None:
        cfg = StorageConfig(postgresql_url="postgres://user:secret@host/db")
        assert "secret" not in repr(cfg)
        assert "postgresql_url" not in repr(cfg)


class TestDetectionBoundaryValid:
    """S-146: Boundary valid tests for new detection params."""

    def test_hst_window_size_at_lower_bound(self) -> None:
        config = _build_detection({"hst_window_size": 1})
        assert config.hst_window_size == 1

    def test_hst_n_trees_at_lower_bound(self) -> None:
        config = _build_detection({"hst_n_trees": 1})
        assert config.hst_n_trees == 1

    def test_dspot_calibration_window_at_lower_bound(self) -> None:
        config = _build_detection({"dspot": {"calibration_window": 1}})
        assert config.dspot_calibration_window == 1

    def test_dspot_initial_percentile_at_lower_bound(self) -> None:
        config = _build_detection({"dspot": {"initial_percentile": 1}})
        assert config.dspot_initial_percentile == 1

    def test_dspot_initial_percentile_at_upper_bound(self) -> None:
        config = _build_detection({"dspot": {"initial_percentile": 100}})
        assert config.dspot_initial_percentile == 100

    def test_markov_min_events_at_lower_bound(self) -> None:
        config = _build_detection({"markov": {"min_events": 1}})
        assert config.markov_min_events == 1


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

    def test_default_late_tolerance(self) -> None:
        config = SeerflowConfig()
        assert config.correlation.late_tolerance_seconds == 30

    def test_negative_late_tolerance_raises(self) -> None:
        from seerflow.config import ConfigError, _build_correlation

        with pytest.raises(ConfigError, match="late_tolerance_seconds must be >= 0"):
            _build_correlation({"late_tolerance_seconds": -1})

    def test_default_rule_dirs_empty(self) -> None:
        config = SeerflowConfig()
        assert config.correlation.rule_dirs == ()

    def test_correlation_config_is_frozen(self) -> None:
        config = SeerflowConfig()
        with pytest.raises(AttributeError):
            config.correlation.window_duration_seconds = 999  # type: ignore[misc]


class TestRiskConfig:
    def test_default_risk_half_life_hours(self) -> None:
        config = SeerflowConfig()
        assert config.detection.risk_half_life_hours == 4

    def test_default_risk_threshold(self) -> None:
        config = SeerflowConfig()
        assert config.detection.risk_threshold == 50.0

    def test_default_risk_max_entities(self) -> None:
        config = SeerflowConfig()
        assert config.detection.risk_max_entities == 10_000

    def test_risk_half_life_hours_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("detection:\n  risk_half_life_hours: 8\n")
        config = load_config(str(yaml_file))
        assert config.detection.risk_half_life_hours == 8

    def test_risk_threshold_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("detection:\n  risk_threshold: 75.0\n")
        config = load_config(str(yaml_file))
        assert config.detection.risk_threshold == 75.0

    def test_risk_max_entities_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("detection:\n  risk_max_entities: 5000\n")
        config = load_config(str(yaml_file))
        assert config.detection.risk_max_entities == 5000

    def test_risk_half_life_hours_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="risk_half_life_hours must be >= 1"):
            _build_detection({"risk_half_life_hours": 0})

    def test_risk_half_life_hours_negative_raises(self) -> None:
        with pytest.raises(ConfigError, match="risk_half_life_hours must be >= 1"):
            _build_detection({"risk_half_life_hours": -1})

    def test_risk_threshold_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="risk_threshold must be > 0"):
            _build_detection({"risk_threshold": 0.0})

    def test_risk_threshold_negative_raises(self) -> None:
        with pytest.raises(ConfigError, match="risk_threshold must be > 0"):
            _build_detection({"risk_threshold": -10.0})

    def test_risk_max_entities_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="risk_max_entities must be >= 1"):
            _build_detection({"risk_max_entities": 0})

    def test_risk_max_entities_negative_raises(self) -> None:
        with pytest.raises(ConfigError, match="risk_max_entities must be >= 1"):
            _build_detection({"risk_max_entities": -5})


class TestGranularHWConfig:
    """S-138: Config params for per-template and per-entity HW detection."""

    def test_defaults(self) -> None:
        config = _build_detection({})
        assert config.max_template_hw == 500
        assert config.max_entity_hw == 500
        assert config.min_events_for_scoring == 50
        assert config.weights_template_volume == 0.15
        assert config.weights_entity_volume == 0.15

    def test_custom_values(self) -> None:
        config = _build_detection(
            {
                "max_template_hw": 1000,
                "max_entity_hw": 2000,
                "min_events_for_scoring": 100,
                "weights_template_volume": 0.10,
                "weights_entity_volume": 0.20,
            }
        )
        assert config.max_template_hw == 1000
        assert config.max_entity_hw == 2000
        assert config.min_events_for_scoring == 100
        assert config.weights_template_volume == 0.10
        assert config.weights_entity_volume == 0.20

    def test_max_template_hw_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="max_template_hw"):
            _build_detection({"max_template_hw": 0})

    def test_max_template_hw_too_high_raises(self) -> None:
        with pytest.raises(ConfigError, match="max_template_hw"):
            _build_detection({"max_template_hw": 100_001})

    def test_max_template_hw_at_lower_bound(self) -> None:
        config = _build_detection({"max_template_hw": 1})
        assert config.max_template_hw == 1

    def test_max_template_hw_at_upper_bound(self) -> None:
        config = _build_detection({"max_template_hw": 100_000})
        assert config.max_template_hw == 100_000

    def test_max_entity_hw_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="max_entity_hw"):
            _build_detection({"max_entity_hw": 0})

    def test_max_entity_hw_too_high_raises(self) -> None:
        with pytest.raises(ConfigError, match="max_entity_hw"):
            _build_detection({"max_entity_hw": 100_001})

    def test_max_entity_hw_at_lower_bound(self) -> None:
        config = _build_detection({"max_entity_hw": 1})
        assert config.max_entity_hw == 1

    def test_max_entity_hw_at_upper_bound(self) -> None:
        config = _build_detection({"max_entity_hw": 100_000})
        assert config.max_entity_hw == 100_000

    def test_min_events_for_scoring_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="min_events_for_scoring"):
            _build_detection({"min_events_for_scoring": 0})

    def test_min_events_for_scoring_negative_raises(self) -> None:
        with pytest.raises(ConfigError, match="min_events_for_scoring"):
            _build_detection({"min_events_for_scoring": -1})

    def test_min_events_for_scoring_at_lower_bound(self) -> None:
        config = _build_detection({"min_events_for_scoring": 1})
        assert config.min_events_for_scoring == 1

    def test_min_events_for_scoring_above_upper_bound_raises(self) -> None:
        with pytest.raises(ConfigError, match="min_events_for_scoring"):
            _build_detection({"min_events_for_scoring": 100_001})

    def test_min_events_for_scoring_at_upper_bound(self) -> None:
        config = _build_detection({"min_events_for_scoring": 100_000})
        assert config.min_events_for_scoring == 100_000

    def test_weights_template_volume_negative_raises(self) -> None:
        with pytest.raises(ConfigError, match="weights_template_volume"):
            _build_detection({"weights_template_volume": -0.1})

    def test_weights_template_volume_nan_raises(self) -> None:
        with pytest.raises(ConfigError, match="weights_template_volume"):
            _build_detection({"weights_template_volume": float("nan")})

    def test_weights_template_volume_inf_raises(self) -> None:
        with pytest.raises(ConfigError, match="weights_template_volume"):
            _build_detection({"weights_template_volume": float("inf")})

    def test_weights_entity_volume_negative_raises(self) -> None:
        with pytest.raises(ConfigError, match="weights_entity_volume"):
            _build_detection({"weights_entity_volume": -0.1})

    def test_weights_entity_volume_nan_raises(self) -> None:
        with pytest.raises(ConfigError, match="weights_entity_volume"):
            _build_detection({"weights_entity_volume": float("nan")})

    def test_weights_entity_volume_inf_raises(self) -> None:
        with pytest.raises(ConfigError, match="weights_entity_volume"):
            _build_detection({"weights_entity_volume": float("inf")})

    def test_weights_template_volume_zero_valid(self) -> None:
        config = _build_detection({"weights_template_volume": 0.0})
        assert config.weights_template_volume == 0.0

    def test_weights_entity_volume_zero_valid(self) -> None:
        config = _build_detection({"weights_entity_volume": 0.0})
        assert config.weights_entity_volume == 0.0

    def test_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "detection:\n"
            "  max_template_hw: 250\n"
            "  max_entity_hw: 300\n"
            "  min_events_for_scoring: 25\n"
            "  weights_template_volume: 0.12\n"
            "  weights_entity_volume: 0.18\n"
        )
        config = load_config(str(yaml_file))
        assert config.detection.max_template_hw == 250
        assert config.detection.max_entity_hw == 300
        assert config.detection.min_events_for_scoring == 25
        assert config.detection.weights_template_volume == 0.12
        assert config.detection.weights_entity_volume == 0.18


class TestHealthBindAddress:
    def test_default_is_localhost(self, tmp_path: Path) -> None:
        config = load_config(None, search_dir=tmp_path)
        assert config.health_bind_address == "127.0.0.1"

    def test_yaml_override(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text('health_bind_address: "0.0.0.0"\n')
        config = load_config(str(yaml_file))
        assert config.health_bind_address == "0.0.0.0"  # noqa: S104

    def test_non_string_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("health_bind_address: 12345\n")
        with pytest.raises(ConfigError, match="health_bind_address"):
            load_config(str(yaml_file))

    def test_invalid_ip_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text('health_bind_address: "not-an-ip"\n')
        with pytest.raises(ConfigError, match="not a valid IP address"):
            load_config(str(yaml_file))


class TestDedupWindowOverrides:
    def test_overrides_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "alerting:\n"
            "  dedup_window_overrides:\n"
            "    hst-anomaly: 300\n"
            "    sigma-brute-force: 3600\n"
        )
        config = load_config(str(yaml_file))
        assert config.alerting.dedup_window_overrides == (
            ("hst-anomaly", 300),
            ("sigma-brute-force", 3600),
        )

    def test_overrides_default_empty(self, tmp_path: Path) -> None:
        config = load_config(None, search_dir=tmp_path)
        assert config.alerting.dedup_window_overrides == ()

    def test_overrides_non_dict_ignored(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("alerting:\n  dedup_window_overrides: not-a-dict\n")
        config = load_config(str(yaml_file))
        assert config.alerting.dedup_window_overrides == ()

    def test_overrides_non_integer_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("alerting:\n  dedup_window_overrides:\n    hst-anomaly: fast\n")
        with pytest.raises(ConfigError, match="must be an integer"):
            load_config(str(yaml_file))

    def test_overrides_zero_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("alerting:\n  dedup_window_overrides:\n    hst-anomaly: 0\n")
        with pytest.raises(ConfigError, match="must be >= 1"):
            load_config(str(yaml_file))

    def test_dedup_window_seconds_zero_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text("alerting:\n  dedup_window_seconds: 0\n")
        with pytest.raises(ConfigError, match="must be an integer >= 1"):
            load_config(str(yaml_file))


class TestWebhookConfigParsing:
    def test_webhooks_parsed_from_yaml(self, tmp_path: Path) -> None:
        from seerflow.alerting import WebhookTarget

        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "alerting:\n"
            "  webhooks:\n"
            "    - url: https://hooks.slack.com/xxx\n"
            "      format: slack\n"
            "    - url: https://outlook.webhook.office.com/xxx\n"
            "      format: teams\n"
            "      min_severity: 4\n"
        )
        config = load_config(str(yaml_file))
        assert len(config.alerting.webhook_targets) == 2
        assert isinstance(config.alerting.webhook_targets[0], WebhookTarget)
        assert config.alerting.webhook_targets[0].url == "https://hooks.slack.com/xxx"
        assert config.alerting.webhook_targets[0].format == "slack"
        assert config.alerting.webhook_targets[0].min_severity == 0
        assert config.alerting.webhook_targets[1].url == "https://outlook.webhook.office.com/xxx"
        assert config.alerting.webhook_targets[1].format == "teams"
        assert config.alerting.webhook_targets[1].min_severity == 4

    def test_webhooks_default_empty(self, tmp_path: Path) -> None:
        config = load_config(None, search_dir=tmp_path)
        assert config.alerting.webhook_targets == ()

    def test_webhook_targets_is_tuple(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "alerting:\n  webhooks:\n    - url: https://hooks.slack.com/xxx\n      format: slack\n"
        )
        config = load_config(str(yaml_file))
        assert isinstance(config.alerting.webhook_targets, tuple)

    def test_webhook_target_frozen(self, tmp_path: Path) -> None:
        from seerflow.alerting import WebhookTarget

        target = WebhookTarget(url="https://example.com", format="json")
        with pytest.raises((AttributeError, TypeError)):
            target.url = "https://other.com"  # type: ignore[misc]

    def test_invalid_url_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="url"):
            _build_alerting({"webhooks": [{"url": "", "format": "slack"}]})

    def test_invalid_format_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="format"):
            _build_alerting({"webhooks": [{"url": "https://example.com", "format": "discord"}]})

    def test_negative_min_severity_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="min_severity"):
            _build_alerting(
                {
                    "webhooks": [
                        {"url": "https://example.com", "format": "json", "min_severity": -1}
                    ]
                }
            )

    def test_json_format_valid(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({"webhooks": [{"url": "https://example.com", "format": "json"}]})
        assert result.webhook_targets[0].format == "json"

    def test_webhook_raw_dicts_preserved(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "alerting:\n  webhooks:\n    - url: https://hooks.slack.com/xxx\n      format: slack\n"
        )
        config = load_config(str(yaml_file))
        assert isinstance(config.alerting.webhooks, tuple)
        assert config.alerting.webhooks[0]["format"] == "slack"

    def test_dashboard_url_read_from_data(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({"dashboard_url": "https://dash.example.com"})
        assert result.dashboard_url == "https://dash.example.com"

    def test_dashboard_url_defaults_to_empty(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({})
        assert result.dashboard_url == ""

    def test_dashboard_url_non_string_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="dashboard_url must be a string"):
            _build_alerting({"dashboard_url": 123})

    def test_dashboard_url_rejects_javascript_scheme(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="must use http or https"):
            _build_alerting({"dashboard_url": "javascript:alert(1)"})

    def test_dashboard_url_rejects_no_hostname(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="must include a hostname"):
            _build_alerting({"dashboard_url": "https://"})

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.0.1",
            "0.0.0.0",  # noqa: S104
            "100.64.0.1",
            "::1",
            "fc00::1",
            "fe80::1",
            "::ffff:100.64.0.1",
        ],
    )
    def test_webhook_private_ip_rejected(self, ip: str) -> None:
        from seerflow.config import ConfigError, _build_alerting

        host = f"[{ip}]" if ":" in ip else ip
        with pytest.raises(ConfigError, match=r"private|reserved|loopback"):
            _build_alerting({"webhooks": [{"url": f"https://{host}/hook", "format": "json"}]})

    def test_webhook_public_ip_accepted(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({"webhooks": [{"url": "https://8.8.8.8/hook", "format": "json"}]})
        assert len(result.webhook_targets) == 1

    def test_webhook_hostname_not_blocked(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting(
            {"webhooks": [{"url": "https://hooks.slack.com/services/T00", "format": "slack"}]}
        )
        assert len(result.webhook_targets) == 1

    def test_dashboard_url_private_ip_rejected(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match=r"private|reserved|loopback"):
            _build_alerting({"dashboard_url": "https://192.168.1.1/dashboard"})

    def test_pagerduty_routing_key_valid_hex(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({"pagerduty_routing_key": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"})
        assert result.pagerduty_routing_key == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"

    def test_pagerduty_routing_key_empty_allowed(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({})
        assert result.pagerduty_routing_key == ""

    def test_pagerduty_routing_key_invalid_format_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="32-character hex"):
            _build_alerting({"pagerduty_routing_key": "not-a-valid-key"})

    def test_pagerduty_routing_key_wrong_length_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="32-character hex"):
            _build_alerting({"pagerduty_routing_key": "abcdef1234"})

    def test_otlp_endpoint_default_empty(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({})
        assert result.otlp_endpoint == ""

    def test_otlp_endpoint_set(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({"otlp_endpoint": "http://collector:4317"})
        assert result.otlp_endpoint == "http://collector:4317"

    def test_otlp_endpoint_bare_host_port_valid(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({"otlp_endpoint": "localhost:4317"})
        assert result.otlp_endpoint == "localhost:4317"

    def test_otlp_endpoint_unsupported_scheme_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="unsupported scheme"):
            _build_alerting({"otlp_endpoint": "ftp://evil.host/exfil"})

    def test_otlp_endpoint_file_scheme_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="unsupported scheme"):
            _build_alerting({"otlp_endpoint": "file:///etc/passwd"})

    def test_otlp_protocol_default_grpc(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({})
        assert result.otlp_protocol == "grpc"

    def test_otlp_protocol_http_valid(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({"otlp_protocol": "http"})
        assert result.otlp_protocol == "http"

    def test_otlp_protocol_invalid_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="otlp_protocol"):
            _build_alerting({"otlp_protocol": "websocket"})

    def test_otlp_export_interval_default_5(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({})
        assert result.otlp_export_interval_seconds == 5

    def test_otlp_export_interval_custom(self) -> None:
        from seerflow.config import _build_alerting

        result = _build_alerting({"otlp_export_interval_seconds": 10})
        assert result.otlp_export_interval_seconds == 10

    def test_otlp_export_interval_zero_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="otlp_export_interval_seconds"):
            _build_alerting({"otlp_export_interval_seconds": 0})

    def test_otlp_export_interval_negative_raises(self) -> None:
        from seerflow.config import ConfigError, _build_alerting

        with pytest.raises(ConfigError, match="otlp_export_interval_seconds"):
            _build_alerting({"otlp_export_interval_seconds": -1})


class TestWebSocketConfig:
    def test_default_ws_fields(self) -> None:
        from seerflow.config import SeerflowConfig

        config = SeerflowConfig()
        assert config.ws_max_connections == 20
        assert config.ws_queue_maxlen == 1000
        assert config.ws_tick_interval_s == 0.01
        assert config.ws_batch_max_events == 10
        assert config.ws_status_interval_s == 5.0

    def test_ws_fields_can_be_overridden(self) -> None:
        from seerflow.config import SeerflowConfig

        config = SeerflowConfig(
            ws_max_connections=5,
            ws_queue_maxlen=500,
            ws_tick_interval_s=0.02,
            ws_batch_max_events=20,
            ws_status_interval_s=10.0,
        )
        assert config.ws_max_connections == 5
        assert config.ws_queue_maxlen == 500

    def test_ws_fields_loaded_from_yaml(self, tmp_path: Path) -> None:
        """YAML ``ws_*`` fields must reach SeerflowConfig via load_config."""
        from seerflow.config import load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text(
            "ws_max_connections: 7\n"
            "ws_queue_maxlen: 250\n"
            "ws_tick_interval_s: 0.05\n"
            "ws_batch_max_events: 3\n"
            "ws_status_interval_s: 2.5\n"
        )
        config = load_config(path=str(yaml_path))
        assert config.ws_max_connections == 7
        assert config.ws_queue_maxlen == 250
        assert config.ws_tick_interval_s == 0.05
        assert config.ws_batch_max_events == 3
        assert config.ws_status_interval_s == 2.5

    def test_ws_max_connections_must_be_positive_int(self, tmp_path: Path) -> None:
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text("ws_max_connections: 0\n")
        with pytest.raises(ConfigError, match="ws_max_connections"):
            load_config(path=str(yaml_path))

    def test_ws_tick_interval_must_be_positive(self, tmp_path: Path) -> None:
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text("ws_tick_interval_s: -0.1\n")
        with pytest.raises(ConfigError, match="ws_tick_interval_s"):
            load_config(path=str(yaml_path))

    def test_ws_queue_maxlen_must_be_int(self, tmp_path: Path) -> None:
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text("ws_queue_maxlen: not-a-number\n")
        with pytest.raises(ConfigError, match="ws_queue_maxlen"):
            load_config(path=str(yaml_path))

    def test_ws_max_connections_rejects_bool(self, tmp_path: Path) -> None:
        """``ws_max_connections: true`` must raise, not silently become 1."""
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text("ws_max_connections: true\n")
        with pytest.raises(ConfigError, match="ws_max_connections"):
            load_config(path=str(yaml_path))

    def test_ws_queue_maxlen_ceiling_enforced(self, tmp_path: Path) -> None:
        """Values above the 100k ceiling must be rejected."""
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text("ws_queue_maxlen: 1000000\n")
        with pytest.raises(ConfigError, match="ws_queue_maxlen"):
            load_config(path=str(yaml_path))

    def test_ws_max_connections_ceiling_enforced(self, tmp_path: Path) -> None:
        """Values above the 1000 ceiling on ws_max_connections must be rejected."""
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text("ws_max_connections: 9999\n")
        with pytest.raises(ConfigError, match="ws_max_connections"):
            load_config(path=str(yaml_path))

    def test_ws_batch_max_events_ceiling_enforced(self, tmp_path: Path) -> None:
        """Values above the 1000 ceiling on ws_batch_max_events must be rejected."""
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text("ws_batch_max_events: 5000\n")
        with pytest.raises(ConfigError, match="ws_batch_max_events"):
            load_config(path=str(yaml_path))

    def test_ws_allowed_origins_defaults_to_empty(self) -> None:
        """Default SeerflowConfig has an empty origins tuple — app.py derives the default."""
        from seerflow.config import SeerflowConfig

        assert SeerflowConfig().ws_allowed_origins == ()

    def test_ws_allowed_origins_loaded_from_yaml(self, tmp_path: Path) -> None:
        """YAML list of origins flows into SeerflowConfig.ws_allowed_origins."""
        from seerflow.config import load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text(
            "ws_allowed_origins:\n  - http://dashboard.local\n  - http://10.0.0.1:8080\n"
        )
        config = load_config(path=str(yaml_path))
        assert config.ws_allowed_origins == (
            "http://dashboard.local",
            "http://10.0.0.1:8080",
        )

    def test_ws_allowed_origins_rejects_non_list(self, tmp_path: Path) -> None:
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text('ws_allowed_origins: "http://localhost"\n')
        with pytest.raises(ConfigError, match="ws_allowed_origins"):
            load_config(path=str(yaml_path))

    def test_ws_allowed_origins_rejects_non_string_items(self, tmp_path: Path) -> None:
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "seerflow.yaml"
        yaml_path.write_text("ws_allowed_origins:\n  - 42\n")
        with pytest.raises(ConfigError, match="ws_allowed_origins"):
            load_config(path=str(yaml_path))


def test_parse_ws_fields_returns_named_tuple() -> None:
    """_parse_ws_fields must return a _WsFields NamedTuple with named access."""
    from seerflow.config import _parse_ws_fields, _WsFields

    result = _parse_ws_fields({})
    assert isinstance(result, _WsFields)
    assert result.ws_max_connections == 20
    assert result.ws_queue_maxlen == 1000
    assert result.ws_tick_interval_s == 0.01
    assert result.ws_batch_max_events == 10
    assert result.ws_status_interval_s == 5.0
    assert result.ws_allowed_origins == ()


def test_ws_filter_min_interval_ms_default_is_100() -> None:
    from seerflow.config import SeerflowConfig

    cfg = SeerflowConfig()
    assert cfg.ws_filter_min_interval_ms == 100


def test_parse_ws_fields_includes_filter_min_interval_ms() -> None:
    from seerflow.config import _parse_ws_fields

    result = _parse_ws_fields({"ws_filter_min_interval_ms": 250})
    assert result.ws_filter_min_interval_ms == 250


def test_ws_filter_min_interval_ms_rejects_negative() -> None:
    import pytest

    from seerflow.config import ConfigError, _parse_ws_fields

    with pytest.raises(ConfigError, match="ws_filter_min_interval_ms"):
        _parse_ws_fields({"ws_filter_min_interval_ms": -1})


def test_ws_filter_min_interval_ms_accepts_zero() -> None:
    """Zero means no throttle — must be accepted."""
    from seerflow.config import _parse_ws_fields

    result = _parse_ws_fields({"ws_filter_min_interval_ms": 0})
    assert result.ws_filter_min_interval_ms == 0


def test_ws_filter_min_interval_ms_rejects_bool() -> None:
    """Bool is an int subclass; must be rejected explicitly."""
    import pytest

    from seerflow.config import ConfigError, _parse_ws_fields

    with pytest.raises(ConfigError, match="ws_filter_min_interval_ms"):
        _parse_ws_fields({"ws_filter_min_interval_ms": True})


# ---------------------------------------------------------------------------
# API hardening (S-181)
# ---------------------------------------------------------------------------


class TestApiConfig:
    def test_api_rate_limit_defaults_from_empty_yaml(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "seerflow.yaml"
        cfg_path.write_text("storage:\n  backend: sqlite\n  path: ':memory:'\n")
        cfg = load_config(cfg_path)
        assert cfg.api_rate_limit_enabled is True
        assert cfg.api_rate_limit_redis_url is None
        assert cfg.api_allowed_origins == ()
        assert cfg.api_list_rate_limit == "60/minute"
        assert cfg.api_detail_rate_limit == "300/minute"
        assert cfg.api_trust_proxy_headers is False

    def test_api_rate_limit_invalid_list_string_rejected(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "seerflow.yaml"
        cfg_path.write_text(
            "storage:\n  backend: sqlite\n  path: ':memory:'\napi_list_rate_limit: '60/blarg'\n"
        )
        with pytest.raises(ConfigError, match="api_list_rate_limit"):
            load_config(cfg_path)

    def test_api_allowed_origins_parsed_as_tuple(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "seerflow.yaml"
        cfg_path.write_text(
            "storage:\n  backend: sqlite\n  path: ':memory:'\n"
            "api_allowed_origins:\n  - https://dash.example.com\n"
        )
        cfg = load_config(cfg_path)
        assert cfg.api_allowed_origins == ("https://dash.example.com",)

    def test_api_rate_limit_redis_url_rejects_empty_string(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "seerflow.yaml"
        cfg_path.write_text(
            "storage:\n  backend: sqlite\n  path: ':memory:'\napi_rate_limit_redis_url: ''\n"
        )
        with pytest.raises(ConfigError, match="api_rate_limit_redis_url"):
            load_config(cfg_path)

    def test_api_allowed_origins_rejects_non_string_entries(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "seerflow.yaml"
        cfg_path.write_text(
            "storage:\n  backend: sqlite\n  path: ':memory:'\napi_allowed_origins:\n  - 42\n"
        )
        with pytest.raises(ConfigError, match="api_allowed_origins"):
            load_config(cfg_path)

    def test_api_allowed_origins_rejects_wildcard(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "seerflow.yaml"
        cfg_path.write_text(
            "storage:\n  backend: sqlite\n  path: ':memory:'\napi_allowed_origins:\n  - '*'\n"
        )
        with pytest.raises(ConfigError, match="must not contain"):
            load_config(cfg_path)

    def test_api_allowed_origins_rejects_schemeless_entries(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "seerflow.yaml"
        cfg_path.write_text(
            "storage:\n  backend: sqlite\n  path: ':memory:'\n"
            "api_allowed_origins:\n  - 'dash.example.com'\n"
        )
        with pytest.raises(ConfigError, match="http://"):
            load_config(cfg_path)


def test_api_coverage_rate_limit_default() -> None:
    cfg = SeerflowConfig()
    assert cfg.api_coverage_rate_limit == "10/minute"


def test_api_coverage_rate_limit_loader_roundtrip(tmp_path: Path) -> None:
    yaml_path = tmp_path / "seerflow.yaml"
    yaml_path.write_text("api_coverage_rate_limit: 5/minute\n")
    cfg = load_config(str(yaml_path))
    assert cfg.api_coverage_rate_limit == "5/minute"


def test_api_coverage_rate_limit_invalid_raises(tmp_path: Path) -> None:
    yaml_path = tmp_path / "seerflow.yaml"
    yaml_path.write_text("api_coverage_rate_limit: not-a-limit\n")
    with pytest.raises(ConfigError, match="api_coverage_rate_limit"):
        load_config(str(yaml_path))


class TestDspotThresholdCapMultiplier:
    def test_default_is_5(self) -> None:
        from seerflow.config import DetectionConfig

        cfg = DetectionConfig()
        assert cfg.dspot_threshold_cap_multiplier == 5.0

    def test_yaml_override(self, tmp_path: Path) -> None:
        from seerflow.config import load_config

        yaml_path = tmp_path / "cfg.yaml"
        yaml_path.write_text(
            "detection:\n"
            "  dspot:\n"
            "    threshold_cap_multiplier: 3.5\n",
            encoding="utf-8",
        )
        cfg = load_config(str(yaml_path))
        assert cfg.detection.dspot_threshold_cap_multiplier == 3.5

    @pytest.mark.parametrize("bad", [0.5, 1.0, 0.0, -1.0])
    def test_numeric_invalid_multiplier_rejected(
        self, tmp_path: Path, bad: float
    ) -> None:
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "cfg.yaml"
        yaml_path.write_text(
            f"detection:\n  dspot:\n    threshold_cap_multiplier: {bad}\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="threshold_cap_multiplier"):
            load_config(str(yaml_path))

    @pytest.mark.parametrize("yaml_special", [".inf", "-.inf", ".nan"])
    def test_nonfinite_multiplier_rejected(
        self, tmp_path: Path, yaml_special: str
    ) -> None:
        from seerflow.config import ConfigError, load_config

        yaml_path = tmp_path / "cfg.yaml"
        yaml_path.write_text(
            f"detection:\n  dspot:\n    threshold_cap_multiplier: {yaml_special}\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="threshold_cap_multiplier"):
            load_config(str(yaml_path))
