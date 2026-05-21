"""Unit tests for SqliteBackend.count_alerts_bucketed (S-154 Task 1)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.models.query import TimeRange
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


HOUR_NS = 3600 * 1_000_000_000


@pytest.fixture
async def sqlite_storage(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    """A fresh SqliteBackend per test."""
    config = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
    b = await SqliteBackend.connect(config)
    yield b
    await b.close()


def _alert(
    ts_ns: int,
    *,
    rule_name: str = "Suspicious PowerShell",
    alert_type: str = "sigma",
) -> Alert:
    return Alert(
        alert_id=f"a-{ts_ns}-{rule_name}-{alert_type}",
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=ts_ns,
        severity_id=SeverityLevel.WARNING,
        rule_name=rule_name,
        description="t",
        entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, "host:web-01")),
        entity_value="web-01",
        entity_type="host",
        contributing_events=(uuid.uuid4(),),
        dedup_key=f"dk-{ts_ns}-{rule_name}-{alert_type}",
    )


@pytest.mark.unit
async def test_count_alerts_bucketed_groups_by_hour(
    sqlite_storage: SqliteBackend,
) -> None:
    base = 1_761_350_400_000_000_000  # arbitrary aligned hour
    for off in (0, 60 * 1_000_000_000, HOUR_NS, HOUR_NS + 1):
        await sqlite_storage.write_alert(_alert(base + off))
    rows = await sqlite_storage.count_alerts_bucketed(
        alert_type="sigma",
        rule_name="Suspicious PowerShell",
        time_range=TimeRange(start_ns=base, end_ns=base + 2 * HOUR_NS),
        bucket_ns=HOUR_NS,
    )
    assert rows == [(base, 2), (base + HOUR_NS, 2)]


@pytest.mark.unit
async def test_count_alerts_bucketed_filters_by_rule_name_and_type(
    sqlite_storage: SqliteBackend,
) -> None:
    base = 1_761_350_400_000_000_000
    await sqlite_storage.write_alert(_alert(base, rule_name="A"))
    await sqlite_storage.write_alert(_alert(base + 1, rule_name="B"))
    await sqlite_storage.write_alert(_alert(base + 2, rule_name="A", alert_type="anomaly"))
    rows = await sqlite_storage.count_alerts_bucketed(
        alert_type="sigma",
        rule_name="A",
        time_range=TimeRange(start_ns=base, end_ns=base + HOUR_NS),
        bucket_ns=HOUR_NS,
    )
    assert rows == [(base, 1)]


@pytest.mark.unit
async def test_count_alerts_bucketed_empty_returns_empty_list(
    sqlite_storage: SqliteBackend,
) -> None:
    rows = await sqlite_storage.count_alerts_bucketed(
        alert_type="sigma",
        rule_name="never-fired",
        time_range=TimeRange(start_ns=0, end_ns=HOUR_NS),
        bucket_ns=HOUR_NS,
    )
    assert rows == []


@pytest.mark.unit
async def test_count_alerts_bucketed_raises_on_non_positive_bucket(
    sqlite_storage: SqliteBackend,
) -> None:
    tr = TimeRange(start_ns=0, end_ns=HOUR_NS)
    with pytest.raises(ValueError):
        await sqlite_storage.count_alerts_bucketed(
            alert_type="sigma",
            rule_name="any",
            time_range=tr,
            bucket_ns=0,
        )
    with pytest.raises(ValueError):
        await sqlite_storage.count_alerts_bucketed(
            alert_type="sigma",
            rule_name="any",
            time_range=tr,
            bucket_ns=-1,
        )


@pytest.mark.unit
async def test_count_alerts_bucketed_half_open_window_boundaries(
    sqlite_storage: SqliteBackend,
) -> None:
    base = 1_761_350_400_000_000_000  # arbitrary aligned hour
    # Alert at exactly start_ns must be included; alert at exactly end_ns excluded.
    await sqlite_storage.write_alert(_alert(base))
    await sqlite_storage.write_alert(_alert(base + HOUR_NS))
    rows = await sqlite_storage.count_alerts_bucketed(
        alert_type="sigma",
        rule_name="Suspicious PowerShell",
        time_range=TimeRange(start_ns=base, end_ns=base + HOUR_NS),
        bucket_ns=HOUR_NS,
    )
    assert rows == [(base, 1)]
