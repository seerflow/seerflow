# Seerflow

A streaming, entity-centric log intelligence agent that detects operational failures and security threats across log sources. Combines traditional ML (fast, cheap) for bulk detection with LLMs (accurate, explanatory) for edge cases and root cause analysis.

## Status

**Alpha** (v0.1.0) — Full ingestion + detection pipeline operational.

[![CI](https://github.com/seerflow/seerflow/actions/workflows/ci.yml/badge.svg)](https://github.com/seerflow/seerflow/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/seerflow)](https://pypi.org/project/seerflow/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](LICENSE)

## Quick Start

```bash
# Install from source
git clone https://github.com/seerflow/seerflow.git
cd seerflow
uv sync

# Copy and edit the example config
cp seerflow.example.yaml seerflow.yaml

# Start the pipeline
uv run python -m seerflow
```

### Command Line

```bash
# Start with default config (seerflow.yaml in current directory)
uv run python -m seerflow

# Start with a specific config file
uv run python -m seerflow --config /path/to/seerflow.yaml

# Show version
uv run python -m seerflow --version
```

### What It Does

1. **Ingests** logs from multiple sources simultaneously (syslog, OTLP gRPC/HTTP, file tailing, webhooks)
2. **Parses** each log line with Drain3 (template extraction) and regex entity extraction (IPs, users, hosts, files, domains, processes)
3. **Scores** events using Half-Space Trees (streaming ML anomaly detection)
4. **Thresholds** scores with biDSPOT (EVT-based auto-threshold -- no manual tuning)
5. **Alerts** on anomalies with template, entities, and score details
6. **Persists** all events to SQLite for later analysis

### Example: Detect Anomalies in Syslog

```yaml
# seerflow.yaml
receivers:
  syslog_enabled: true
  syslog_udp_port: 5514       # use high port to avoid root
  otlp_grpc_enabled: false
  otlp_http_enabled: false
  webhook_enabled: false

detection:
  hst_window_size: 100         # lower for faster calibration
  dspot:
    calibration_window: 200
    risk_level: 0.01           # more sensitive for testing
```

```bash
# Terminal 1: Start Seerflow
uv run python -m seerflow

# Terminal 2: Send normal traffic
for i in $(seq 1 300); do
    echo "<134>1 2026-03-24T19:00:00Z web nginx $i - - GET /api/v$((i%5)) 200 ${i}ms" \
        | nc -u -w1 127.0.0.1 5514
done

# Terminal 2: Send anomalies
echo '<11>1 2026-03-24T19:01:00Z db postgres 999 - - FATAL connection limit exceeded 847/100' \
    | nc -u -w1 127.0.0.1 5514
```

Output:
```
INFO Seerflow 0.1.0 starting
INFO Receivers: syslog
INFO Pipeline running — Ctrl+C to stop
WARNING ANOMALY [syslog] score=0.952 threshold=0.009 dir=upper
WARNING   template: [7] <*> <*> postgres <*> - - FATAL connection limit exceeded <*>
WARNING   message:  <11>1 2026-03-24T19:01:00Z db postgres 999 - - FATAL connection limit exceeded 847/100
WARNING   entities: 203.0.113.1
```

### Shutdown Summary

Press Ctrl+C to see session stats:

```
INFO --- Session Summary ---
INFO   Events processed: 312
INFO   Anomalies detected: 10
INFO   Unique templates: 7
INFO   Duration: 45.3s
INFO   Throughput: 7 events/sec
INFO Seerflow stopped
```

## Configuration

See [SETTINGS.md](SETTINGS.md) for the complete configuration reference.

All settings are optional -- Seerflow runs with sensible defaults (zero-config).

Key config sections:
- **receivers** -- syslog, OTLP gRPC/HTTP, file tailing, webhooks (enable/disable + ports)
- **detection** -- HST window size, DSPOT calibration, scoring weights
- **storage** -- SQLite (default) or PostgreSQL
- **alerting** -- dedup window, webhook/PagerDuty targets

## Receivers

| Receiver | Port | Protocol | Status |
|----------|------|----------|--------|
| Syslog UDP/TCP | 514 (5514) | RFC 5424/3164 | Done |
| OTLP gRPC | 4317 | Protobuf | Done |
| OTLP HTTP | 4318 | Protobuf + JSON | Done |
| File tailing | -- | Glob + watchfiles | Done |
| Webhooks | 8081 | JSON/form + auth | Done |

## Detection Pipeline

```
Log Sources → Receivers → Drain3 Parser → Entity Extractor → HST Scorer → biDSPOT Threshold → Alert
                                ↓                ↓                ↓              ↓
                          template_id       IPs, users      anomaly score   is_anomaly?
                          template_str      hosts, files    [0.0 - 1.0]    upper/lower
                          template_params   domains, procs
```

- **Drain3**: Streaming log template extraction (120K msgs/sec)
- **Half-Space Trees**: Online ML anomaly detection via River (constant time/memory)
- **biDSPOT**: Bidirectional EVT auto-threshold (upper spikes + lower drops)
- **DetectionEnsemble**: Orchestrates detectors + thresholds per source

## Development

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run quality gates
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ && uv run bandit -r src/ -c pyproject.toml && uv run pytest --cov=src/seerflow --cov-fail-under=90
```

### Project Structure

```
src/seerflow/
    __main__.py      # CLI entry point (config → pipeline → detection → storage)
    cli.py           # argparse (--config, --version)
    config.py        # YAML config loader with ${ENV_VAR} interpolation
    pipeline.py      # Pipeline builder + consumer loop
    models/          # SeerflowEvent, Alert, entity structs (msgspec)
    storage/
        protocols.py # Protocol interfaces (LogStore, AlertStore, ModelStore, EntityStore)
        sqlite.py    # SQLite backend (WAL, FTS5, WriteBuffer)
    receivers/
        base.py      # RawEvent dataclass, Receiver protocol
        manager.py   # ReceiverManager (bounded queue, backpressure, shutdown)
        syslog.py    # UDP/TCP syslog (RFC 5424/3164)
        otlp_grpc.py # OTLP gRPC receiver (protobuf LogRecord)
        otlp_http.py # OTLP HTTP receiver (/v1/logs, protobuf + JSON)
        file_tail.py # File tailing (glob, rotation, checkpoint)
        webhook.py   # Webhooks (JSON/form, field mapping, auth)
    parsing/
        drain.py     # Drain3 wrapper for template extraction
        entities.py  # Regex entity extraction (6 types)
        normalizer.py # EventNormalizer: RawEvent → SeerflowEvent
    detection/
        protocols.py # Detector Protocol (score, learn, serialize, deserialize)
        hst.py       # Half-Space Trees detector (River)
        threshold.py # biDSPOT auto-threshold (scipy GPD)
        ensemble.py  # DetectionEnsemble orchestrator
tests/
    unit/            # 670+ unit tests
    integration/     # Integration tests (multi-source, real SQLite)
    benchmarks/      # Throughput benchmarks (pytest-benchmark)
```

### Benchmarks

```bash
uv run pytest tests/benchmarks/ --benchmark-autosave
uv run pytest tests/benchmarks/ --benchmark-compare
```

| Component | Throughput |
|-----------|-----------|
| Syslog parse | ~561K msgs/sec |
| Drain3 templates | ~120K msgs/sec |
| Entity extraction | ~41K msgs/sec |
| Full normalizer | ~39.5K msgs/sec |

## License

[AGPL-3.0](LICENSE)
