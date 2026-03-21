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

```bash
# Run benchmarks and save baseline
uv run pytest tests/benchmarks/ --benchmark-autosave

# Compare against previous run
uv run pytest tests/benchmarks/ --benchmark-compare=0001

# Run only benchmarks (skip slow tests)
uv run pytest tests/benchmarks/ -m "not slow"
```

#### Reading benchmark output

Each benchmark processes 10K messages per call. The output table shows:

| Column | Meaning |
|--------|---------|
| **Min/Max/Mean** | Wall-clock time per call (lower is faster) |
| **StdDev** | Standard deviation across rounds. Lower = more consistent |
| **Rounds** | How many times the function was called. More rounds = better statistical confidence. Minimum 10 (configured in `pyproject.toml`) |
| **Iterations** | Calls per round. Stays at 1 when each call is already measurable (>1ms) |
| **OPS** | Operations per second (`1 / Mean`). Multiply by 10,000 for messages/sec throughput |
| **IQR** | Interquartile range (middle 50% spread). More robust than StdDev for outlier-heavy runs |
| **Outliers** | Format `A;B` where A = mild (>1 StdDev from mean), B = extreme (>1.5 IQR from quartiles) |

**Colors and ratios:** Green = fastest (best) in that column, baseline `(1.0)`. Red = slowest. Parenthesized numbers are ratios relative to fastest (e.g., `(4.69)` = 4.69x slower).

**Throughput interpretation:** OPS x 10,000 = messages/sec. For example, OPS 56.14 = ~561K syslog parses/sec.

#### Example output

```
Name (time in ms)                Min       Max      Mean    StdDev    Rounds  OPS
test_parse_throughput (syslog)  17.08    19.52    17.81     0.54        57   56.14
test_parse_throughput (drain)   80.18    92.50    83.34     3.43        11   12.00
test_extraction_throughput     239.00   246.02   243.01     2.68        10    4.12
test_normalize_throughput      247.86   263.30   252.99     6.29        10    3.95
```

#### Sync vs async benchmarks

**4 sync benchmarks** (drain, entity, normalizer, syslog parse) use the `pytest-benchmark` fixture:
- Support `--benchmark-autosave` and `--benchmark-compare`
- Statistical analysis (mean, stddev, rounds, outliers)
- Throughput floor assertions via `benchmark.stats["mean"]`

**11 async benchmarks** (SQLite writes, queries, alerts, UDP receive) use manual `time.perf_counter()`:
- Floor assertions catch regressions in CI (e.g., `assert rate >= 5000`)
- Do not produce `pytest-benchmark` JSON data
- Reason: the `benchmark` fixture calls functions in a tight loop, which is incompatible with asyncio event loops and aiosqlite connections

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
