"""Unit tests for SqliteBackend.count_alerts_grouped (S-229 / SEE-240 Task 1)."""

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
async def test_count_alerts_grouped_empty_returns_empty_dict(
    sqlite_storage: SqliteBackend,
) -> None:
    out = await sqlite_storage.count_alerts_grouped(
        alert_type="sigma",
        time_range=TimeRange(start_ns=0, end_ns=HOUR_NS),
        group_by="rule_name",
    )
    assert out == {}


@pytest.mark.unit
async def test_count_alerts_grouped_single_rule(
    sqlite_storage: SqliteBackend,
) -> None:
    base = 1_761_350_400_000_000_000
    for off in (0, 1, 2):
        await sqlite_storage.write_alert(_alert(base + off))
    out = await sqlite_storage.count_alerts_grouped(
        alert_type="sigma",
        time_range=TimeRange(start_ns=base, end_ns=base + HOUR_NS),
        group_by="rule_name",
    )
    assert out == {"Suspicious PowerShell": 3}


@pytest.mark.unit
async def test_count_alerts_grouped_multi_rule_mixed_type(
    sqlite_storage: SqliteBackend,
) -> None:
    base = 1_761_350_400_000_000_000
    await sqlite_storage.write_alert(_alert(base, rule_name="A"))
    await sqlite_storage.write_alert(_alert(base + 1, rule_name="A"))
    await sqlite_storage.write_alert(_alert(base + 2, rule_name="B"))
    await sqlite_storage.write_alert(_alert(base + 3, rule_name="A", alert_type="anomaly"))
    out = await sqlite_storage.count_alerts_grouped(
        alert_type="sigma",
        time_range=TimeRange(start_ns=base, end_ns=base + HOUR_NS),
        group_by="rule_name",
    )
    assert out == {"A": 2, "B": 1}


@pytest.mark.unit
async def test_count_alerts_grouped_half_open_window(
    sqlite_storage: SqliteBackend,
) -> None:
    base = 1_761_350_400_000_000_000
    # Alert at exactly start_ns is included; alert at exactly end_ns excluded.
    await sqlite_storage.write_alert(_alert(base, rule_name="A"))
    await sqlite_storage.write_alert(_alert(base + HOUR_NS, rule_name="A"))
    out = await sqlite_storage.count_alerts_grouped(
        alert_type="sigma",
        time_range=TimeRange(start_ns=base, end_ns=base + HOUR_NS),
        group_by="rule_name",
    )
    assert out == {"A": 1}


@pytest.mark.unit
async def test_count_alerts_grouped_rejects_unknown_group_by(
    sqlite_storage: SqliteBackend,
) -> None:
    with pytest.raises(ValueError, match="unsupported group_by"):
        await sqlite_storage.count_alerts_grouped(
            alert_type="sigma",
            time_range=TimeRange(start_ns=0, end_ns=HOUR_NS),
            group_by="entity_value; DROP TABLE alerts",  # type: ignore[arg-type]
        )
