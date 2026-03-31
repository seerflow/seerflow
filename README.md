# Seerflow

A streaming, entity-centric log intelligence agent that detects operational failures and security threats across log sources. Combines traditional ML (fast, cheap) for bulk detection with Sigma rules (3,000+ community detections) for known threat patterns.

## Status

**Alpha** — Full ingestion + detection + Sigma rules pipeline operational.

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
uv run python -m seerflow start
```

### Command Line

```bash
# Start with default config (seerflow.yaml in current directory)
uv run python -m seerflow start

# Start with a specific config file
uv run python -m seerflow --config /path/to/seerflow.yaml start

# Show version
uv run python -m seerflow --version
```

### Docker

```bash
# Build and run with SQLite defaults (zero config)
docker compose up -d

# Run with PostgreSQL (set password first)
export POSTGRES_PASSWORD=your-secure-password
docker compose --profile postgres up -d

# Or run standalone from a registry image
docker run -p 8080:8080 -p 4317:4317 -p 514:514/udp seerflow/seerflow

# Mount a custom config
docker run -v ./seerflow.yaml:/app/seerflow.yaml:ro seerflow/seerflow
```

### What It Does

1. **Ingests** logs from multiple sources simultaneously (syslog, OTLP gRPC/HTTP, file tailing, webhooks)
2. **Parses** each log line with Drain3 (template extraction) and regex entity extraction (IPs, users, hosts, files, domains, processes)
3. **Resolves** entities to deterministic UUID5 IDs for cross-source correlation
4. **Scores** events with an ML ensemble: Half-Space Trees (content), Holt-Winters (volume), CUSUM (change), Markov chains (sequence) -- blended with z-normalization
5. **Thresholds** scores with biDSPOT (EVT-based auto-threshold -- no manual tuning)
6. **Evaluates** 63 bundled Sigma rules (Linux, web, DNS, process, network) with MITRE ATT&CK tagging
7. **Graphs** entity relationships with igraph -- PageRank, Louvain, fan-out, betweenness centrality
8. **Accumulates** per-entity risk with exponential decay -- catches slow-burn multi-step attacks
9. **Alerts** on anomalies, Sigma matches, and risk threshold exceedances
10. **Persists** all events, alerts, graph edges, and ML model state to SQLite

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
uv run python -m seerflow start

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
INFO Seerflow 0.3.0 starting
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
- **detection** -- HST window size, DSPOT calibration, scoring weights, custom Sigma rule directories
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
Log Sources → Receivers → Drain3 → UUID5 Entities → ML Ensemble → Sigma Rules
                                        ↓                ↓              ↓
                                  Entity Graph      blended score   ATT&CK tags
                                  Window Buffer     [0.0 - 1.0]    tactic/technique
                                  Risk Register         ↓              ↓
                                        ↓          Risk Accumulation → Alert
                                  PageRank, Louvain
                                  Fan-out, Betweenness
```

- **Drain3**: Streaming log template extraction (120K msgs/sec)
- **UUID5 Entity Resolution**: Deterministic cross-source entity IDs (same entity = same UUID)
- **Half-Space Trees**: Content anomaly detection via River (constant time/memory)
- **Holt-Winters**: Volume anomaly detection (trend + seasonal decomposition)
- **CUSUM**: Change-point detection (bidirectional cumulative sum)
- **Markov Chains**: Sequence anomaly detection (per-entity transition matrices)
- **biDSPOT**: Bidirectional EVT auto-threshold (upper spikes + lower drops)
- **DetectionEnsemble**: Orchestrates all detectors + blended scoring per source
- **Sigma Engine**: 63 bundled SigmaHQ rules with logsource-indexed dispatch
- **Entity Graph**: igraph-backed relationship graph with typed edges + 6 algorithms
- **Risk Accumulation**: Per-entity risk register with exponential decay + configurable threshold
- **Sliding Window**: Per-entity event buffer with watermark-based late arrival tolerance

## Development

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run quality gates
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ && uv run bandit -r src/ -c pyproject.toml && uv run pytest --cov=src/seerflow --cov-fail-under=95
```

### Project Structure

```
src/seerflow/
    __main__.py      # CLI entry point (config → pipeline → detection → storage)
    cli.py           # argparse (--config, --version)
    config.py        # YAML config loader with ${ENV_VAR} interpolation
    models/          # SeerflowEvent, Alert, entity structs (msgspec)
    storage/
        protocols.py # Protocol interfaces (LogStore, AlertStore, ModelStore, EntityStore)
        sqlite.py    # SQLite backend (WAL, FTS5, WriteBuffer)
        migrations.py # Schema versioning + forward-only migration runner
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
        entities.py  # Regex entity extraction (6 types, params-aware tagging)
        normalizer.py # EventNormalizer: RawEvent → SeerflowEvent
    detection/
        protocols.py # Detector Protocol (score, learn, serialize, deserialize)
        hst.py       # Half-Space Trees detector (River)
        threshold.py # biDSPOT auto-threshold (scipy GPD)
        ensemble.py  # DetectionEnsemble orchestrator (4 detectors + blended scoring)
    sigma/
        engine.py    # SigmaEngine: rule loading, logsource dispatch, evaluation
        matcher.py   # Custom detection matcher (condition tree walker, regex cache)
        pipeline.py  # pySigma processing pipeline (22 field mappings)
        attack.py    # MITRE ATT&CK tactic/technique extraction
        bundled.py   # Bundled rule path discovery (importlib.resources)
        loader.py    # Custom rule directory discovery + validation
        rules/       # 63 curated SigmaHQ YAML rules (linux, web, dns, process, network)
    graph/
        entity_graph.py # igraph wrapper: vertices, edges, queries, algorithms
        edges.py     # Typed edge inference from entity pairs
        algorithms.py # PageRank, Louvain, fan-out, fan-in, betweenness, ego-graph
    correlation/
        window.py    # Per-entity sliding window buffer (deque, LRU eviction)
        watermark.py # Watermark-based late arrival tolerance
        risk.py      # Risk accumulation with exponential decay
    pipeline/
        handler.py   # Event handler: parse → detect → graph → correlate → store
        run.py       # Pipeline runner (config → receivers → handler → storage)
tests/
    unit/            # 1200+ unit tests
    integration/     # Integration tests (pipeline, graph, correlation, real SQLite)
    benchmarks/      # Throughput benchmarks (pytest-benchmark, CI history tracking)
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
| **Full pipeline** (parse + ML + Sigma + storage) | **~1,800 events/sec** |

## License

[AGPL-3.0](LICENSE)
