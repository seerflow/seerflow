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

Each benchmark function processes **10,000 messages in a single call**. So when you see `Min 17.08 ms`, that means 10K syslog messages were parsed in 17.08 milliseconds (not one message).

| Column | Meaning |
|--------|---------|
| **Min/Max/Mean** | Wall-clock time for one call that processes 10K messages. Lower is faster. `Min 17.08 ms` = 10K messages parsed in 17ms = ~585K msgs/sec |
| **StdDev** | Standard deviation across rounds. Lower = more consistent performance |
| **Rounds** | How many times pytest-benchmark called the function. Each round is one full 10K-message run. More rounds = more data points = tighter statistics. Minimum 10 rounds (configured in `pyproject.toml`). Fast tests get more rounds automatically (e.g., syslog parse ~17ms gets 50+ rounds; normalizer ~250ms gets exactly 10) |
| **Iterations** | How many times the function is called within a single round. Stays at 1 here because each call is already slow enough to measure accurately (>1ms). pytest-benchmark would increase this for sub-microsecond functions |
| **OPS** | Operations per second (`1 / Mean`). Each "operation" is one 10K-message run. To get messages/sec: OPS x 10,000. Example: OPS 56.14 = ~561K syslog parses/sec |
| **IQR** | Interquartile range -- the spread of the middle 50% of measurements. More robust than StdDev when there are outliers |
| **Outliers** | Format `A;B` where A = mild outliers (>1 StdDev from mean), B = extreme outliers (>1.5 IQR from quartiles) |

**Values with parenthesized ratios** like `17.08 (1.0)` or `80.18 (4.69)`:
- The number before the parenthesis is the **actual value** (e.g., 17.08 milliseconds)
- `(1.0)` means this is the **fastest/best** in that column -- the baseline
- `(4.69)` means this is **4.69x slower** than the baseline
- Green-colored values = fastest. Red = slowest

**Throughput cheat sheet:**

| Benchmark | Mean | Throughput |
|-----------|------|-----------|
| Syslog parse | 17.8 ms | ~561K msgs/sec |
| Drain parse | 83.3 ms | ~120K msgs/sec |
| Entity extraction | 243.0 ms | ~41K msgs/sec |
| Normalizer (full pipeline) | 253.0 ms | ~39.5K msgs/sec |

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
