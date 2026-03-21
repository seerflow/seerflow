"""Shared fixtures for benchmark tests."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from _pytest.terminal import TerminalReporter

_BENCHMARK_GUIDE = """\

================================ seerflow benchmark guide ================================
  Each benchmark processes 10,000 messages per call.
  To convert OPS to throughput: OPS x 10,000 = messages/sec

  Columns:
    Min/Max/Mean  Time for one 10K-message call (lower = faster)
    StdDev        Consistency across rounds (lower = more stable)
    Rounds        Number of repeated measurements (min 10, fast tests get more)
    OPS           Calls/sec (1/Mean). OPS 56 = 56 calls/sec = 560K msgs/sec
    (1.0)         Baseline -- fastest value in column. (4.69) = 4.69x slower

  Colors: green = fastest, red = slowest
  Outliers A;B: A = mild (>1 StdDev), B = extreme (>1.5 IQR)
  Async benchmarks use manual timing -- see README for details
==========================================================================================
"""


def pytest_unconfigure(config: pytest.Config) -> None:
    """Print benchmark guide after all output including the stats table."""
    reporter: TerminalReporter | None = config.pluginmanager.get_plugin(
        "terminalreporter",
    )
    if reporter is not None:
        for line in _BENCHMARK_GUIDE.splitlines():
            reporter.write_line(line)


def make_event(
    *,
    message: str = "bench event",
    severity: SeverityLevel = SeverityLevel.INFORMATIONAL,
    entity_refs: tuple[str, ...] = (),
    source_type: str = "bench",
) -> SeerflowEvent:
    """Create a minimal SeerflowEvent for benchmarking."""
    now_ns = 1_710_000_000_000_000_000
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=now_ns,
        observed_ns=now_ns + 1_000_000,
        severity_id=severity,
        message=message,
        source_type=source_type,
        source_id="bench",
        entity_refs=entity_refs,
    )


def make_alert(
    *,
    alert_type: str = "ml",
    message: str = "bench alert",
    entity_uuid: str = "entity-aaa",
    dedup_key: str = "",
    severity: SeverityLevel = SeverityLevel.WARNING,
) -> Alert:
    """Create a minimal Alert for benchmarking."""
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type=alert_type,
        timestamp_ns=1_710_000_000_000_000_000,
        severity_id=severity,
        rule_name="bench-rule",
        description=message,
        entity_uuid=entity_uuid,
        entity_value="192.168.1.1",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        dedup_key=dedup_key or str(uuid.uuid4()),
    )


@pytest.fixture
async def backend() -> AsyncIterator[SqliteBackend]:
    """Create an in-memory SqliteBackend for benchmarks."""
    config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
    b = await SqliteBackend.connect(config)
    yield b
    await b.close()
