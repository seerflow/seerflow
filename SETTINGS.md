# Seerflow Settings Reference

Complete reference for all configuration keys in `seerflow.yaml`.
All settings are optional — sensible defaults apply when omitted.

## Top-level

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `dashboard_port` | int | `8080` | HTTP port for the Seerflow dashboard UI. |
| `log_level` | string | `"INFO"` | Application log verbosity. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |

## `storage`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `backend` | string | `"sqlite"` | Storage engine. `sqlite` (zero-config) or `postgresql` (production scale). |
| `data_dir` | string | `~/.local/share/seerflow` | Root data directory. Respects `$XDG_DATA_HOME` and `$SEERFLOW_DATA_DIR`. |
| `sqlite_path` | string | `<data_dir>/seerflow.db` | Absolute path to the SQLite database file. Derived from `data_dir` when omitted. |
| `postgresql_url` | string | `""` | PostgreSQL DSN, e.g. `postgresql://user:pass@host/db`. Required when `backend=postgresql`. Supports `${ENV_VAR}` interpolation. |

## `receivers`

### Network binding

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `bind_addr` | string | `"0.0.0.0"` | IP address all receivers bind to. Set to `127.0.0.1` to restrict to localhost. |
| `queue_maxsize` | int | `10000` | Maximum events in the internal receiver queue before back-pressure is applied. |

### Syslog

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `syslog_enabled` | bool | `true` | Enable the syslog listener (both UDP and TCP when their respective flags are set). |
| `syslog_udp_port` | int | `514` | UDP port for syslog (RFC 3164 / RFC 5424). |
| `syslog_tcp_port` | int | `601` | TCP port for syslog (RFC 6587). |
| `syslog_tcp_enabled` | bool | `true` | Enable TCP syslog. Set `false` to accept UDP only while `syslog_enabled=true`. |

### OpenTelemetry gRPC

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `otlp_grpc_enabled` | bool | `true` | Enable the OTLP/gRPC receiver. |
| `otlp_grpc_port` | int | `4317` | gRPC port (standard OTLP port). |
| `otlp_grpc_max_workers` | int | `4` | Thread-pool size for the gRPC server. |

### OpenTelemetry HTTP

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `otlp_http_enabled` | bool | `true` | Enable the OTLP/HTTP receiver. |
| `otlp_http_port` | int | `4318` | HTTP port (standard OTLP/HTTP port). |
| `otlp_http_max_request_bytes` | int | `4194304` | Maximum allowed request body size in bytes (default 4 MiB). Raise for high-volume batches. |

### File tailing

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `file_paths` | list[string] | `[]` | Glob patterns for log files to tail, e.g. `/var/log/*.log`. |
| `file_checkpoint_dir` | string | `""` | Directory to persist tail offsets across restarts. Empty string disables checkpointing. |
| `file_debounce_ms` | int | `1600` | Milliseconds to wait after the last write event before re-reading a file. |
| `allowed_log_roots` | list[string] | `[]` | Security allowlist: `file_paths` must fall under one of these directory prefixes. |

### Webhook HTTP receiver

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `webhook_enabled` | bool | `false` | Enable the inbound HTTP webhook listener. |
| `webhook_port` | int | `8081` | Port for the webhook HTTP server. Must be 1–65535. |
| `webhooks` | list[mapping] | `[]` | Per-endpoint webhook configurations (see sub-table below). |

#### `receivers.webhooks[]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `path` | string | `"/ingest/webhook"` | URL path that this endpoint listens on. |
| `auth_header` | string | `""` | HTTP header name used for token authentication. Must be paired with `auth_token`. |
| `auth_token` | string | `""` | Expected token value. Supports `${ENV_VAR}` interpolation. Must be paired with `auth_header`. |
| `field_mapping` | mapping | `{}` | Maps Seerflow field names to JSON path keys in the incoming payload. |
| `source_id` | string | `"webhook"` | Identifier applied to events received on this endpoint. |

## `detection`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `hst_window_size` | int | `1000` | Sliding window size for Half-Space Trees anomaly detector. |
| `hst_n_trees` | int | `25` | Number of trees in the Half-Space Trees ensemble. |
| `dspot.calibration_window` | int | `1000` | Minimum events required before DSPOT auto-threshold activates. |
| `dspot.risk_level` | float | `0.0001` | Target false-positive rate for DSPOT (1 alert per 10,000 normal events). |
| `dspot.initial_percentile` | int | `98` | Percentile used to seed the initial DSPOT threshold. |
| `sigma_rules_dirs` | list[string] | `[]` | Additional directories containing custom Sigma rule YAML files. Loaded alongside the 63 bundled rules. |
| `weights_content` | float | `0.30` | Blend weight for the content (Half-Space Trees) anomaly score. |
| `weights_volume` | float | `0.25` | Blend weight for the volume (Holt-Winters) anomaly score. |
| `weights_sequence` | float | `0.25` | Blend weight for the sequence (Markov chain) anomaly score. |
| `weights_pattern` | float | `0.20` | Blend weight for the pattern (CUSUM) anomaly score. |

## `alerting`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `dedup_window_seconds` | int | `900` | Seconds before the same alert can fire again (deduplication window, default 15 min). |
| `pagerduty_routing_key` | string | `""` | PagerDuty Events API v2 routing key. Supports `${ENV_VAR}` interpolation. |
| `webhooks` | list[mapping] | `[]` | Outbound alert webhook targets. Each entry requires `url` and optionally `format` (`slack`, `teams`, or omit for generic JSON). |

## `llm`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `backend` | string | `""` | LLM inference backend. One of `llamacpp`, `ollama`, `cloud`. Empty disables LLM features. |
| `model_path` | string | `""` | Path to a local GGUF model file (used when `backend=llamacpp`). |
| `ollama_url` | string | `"http://localhost:11434"` | Base URL of the Ollama API server (used when `backend=ollama`). |

## `correlation`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `window_duration_seconds` | int | `1800` | Sliding window duration for entity-temporal correlation (default 30 min). |
| `max_events_per_entity` | int | `1000` | Maximum events per entity in the correlation window buffer. |
| `max_entities` | int | `10000` | Maximum number of entities tracked in the window buffer (LRU eviction). |
| `late_tolerance_seconds` | int | `30` | Watermark tolerance for late-arriving events (events beyond tolerance skipped for correlation). |
