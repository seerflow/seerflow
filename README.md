# Seerflow

A streaming, entity-centric log intelligence agent that detects operational failures and security threats across log sources. Combines traditional ML (fast, cheap) for bulk detection with LLMs (accurate, explanatory) for edge cases and root cause analysis.

## Status

**Pre-Alpha** (v0.1.0) -- Sprint 2 of 15 in progress.

[![CI](https://github.com/seerflow/seerflow/actions/workflows/ci.yml/badge.svg)](https://github.com/seerflow/seerflow/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/seerflow)](https://pypi.org/project/seerflow/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](LICENSE)

## Quick Start

```bash
pip install seerflow
```

Or from source:

```bash
git clone https://github.com/seerflow/seerflow.git
cd seerflow
uv sync
uv run seerflow
```

## Development

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run bandit -r src/ -c pyproject.toml

# Run all gates at once
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ && uv run bandit -r src/ -c pyproject.toml && uv run pytest --cov=src/seerflow --cov-fail-under=90
```

### Benchmarks

Sync benchmarks (parsing, entity extraction, normalization) use `pytest-benchmark` for regression tracking:

```bash
# Run benchmarks and save baseline
uv run pytest tests/benchmarks/ --benchmark-autosave

# Compare against previous run
uv run pytest tests/benchmarks/ --benchmark-compare=0001

# Run only benchmarks (skip slow tests)
uv run pytest tests/benchmarks/ -m "not slow"
```

Async benchmarks (SQLite writes, queries, UDP receive) use manual timing with floor assertions. These run alongside the sync benchmarks but do not produce `pytest-benchmark` data -- the `benchmark` fixture is incompatible with asyncio event loops.

### Project Structure

```
src/seerflow/
    models/          # SeerflowEvent, Alert, query structs (msgspec)
    config.py        # YAML config loader with env var interpolation
    storage/
        protocols.py # Protocol interfaces (LogStore, AlertStore, ModelStore, EntityStore)
        sqlite.py    # SQLite backend (WAL, FTS5, WriteBuffer)
    receivers/
        base.py      # RawEvent dataclass, Receiver protocol
        manager.py   # ReceiverManager (bounded queue, backpressure)
        syslog.py    # UDP/TCP syslog receiver (RFC 5424/3164)
    parsing/
        _constants.py # Shared constants (MAX_MESSAGE_LEN, MAX_RAW_BYTES, etc.)
        drain.py     # Drain3 wrapper for template extraction
        entities.py  # Regex entity extraction (IPs, users, hosts, files, domains)
        normalizer.py # EventNormalizer: RawEvent -> SeerflowEvent
tests/
    unit/            # Unit tests
    integration/     # Integration tests (real SQLite)
    benchmarks/      # Throughput benchmarks
```

## Architecture

```
Log Sources -> Receivers -> EventNormalizer -> Detection -> Alerting
                  |              |
             RawEvent    SeerflowEvent
             (bytes)     (canonical struct)
```

- **Receivers**: Syslog (UDP/TCP), file tailing, OTel (planned)
- **Parsing**: Drain3 template extraction + regex entity extraction
- **Detection**: Half-Space Trees, Holt-Winters, Sigma rules (planned)
- **Storage**: SQLite (default) or PostgreSQL (planned), Protocol-based interfaces

## License

[AGPL-3.0](LICENSE)
