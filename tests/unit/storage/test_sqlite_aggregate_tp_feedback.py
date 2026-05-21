"""Unit tests for ``SqliteBackend.aggregate_tp_feedback`` (S-100).

Covers AC2: pattern grouping by ``(alert_type, rule_name, entity_type)``,
``tp_count >= min_tp`` filter, latest-verdict-per-alert dedup, ``window_ns``
clipping, and the ``contributing_alert_ids`` cap.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture
async def sqlite_storage(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    config = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "agg.db"))
    backend = await SqliteBackend.connect(config)
    yield backend
    await backend.close()


def _alert(
    *,
    alert_id: str,
    alert_type: str = "ml",
    rule_name: str = "hst-anomaly",
    entity_type: str = "ip",
) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name=rule_name,
        description="t",
        entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, alert_id)),
        entity_value=f"v-{alert_id}",
        entity_type=entity_type,  # type: ignore[arg-type]
        contributing_events=(uuid.uuid4(),),
        dedup_key=f"hst:1:syslog:{alert_id}",
    )


async def test_empty_store_returns_empty_tuple(sqlite_storage: SqliteBackend) -> None:
    """AC2: no alerts → empty result."""
    result = await sqlite_storage.aggregate_tp_feedback(min_tp=3)
    assert result == ()


async def test_three_tps_same_pattern_returns_one_row(
    sqlite_storage: SqliteBackend,
) -> None:
    """AC2: three TPs on the same pattern → one eligible row."""
    for i in range(3):
        alert = _alert(alert_id=f"a-{i}")
        await sqlite_storage.write_alert(alert)
        await sqlite_storage.append_feedback_event(
            alert_id=f"a-{i}",
            feedback="tp",
            note="",
            origin="dashboard",
            submitted_at_ns=1_000 + i,
        )
    result = await sqlite_storage.aggregate_tp_feedback(min_tp=3)
    assert len(result) == 1
    row = result[0]
    assert row.pattern_key == "ml:hst-anomaly:ip"
    assert row.tp_count == 3
    assert row.most_recent_tp_ns == 1_002
    # contributing_alert_ids ordered newest TP first
    assert row.contributing_alert_ids == ("a-2", "a-1", "a-0")


async def test_below_threshold_filtered_out(sqlite_storage: SqliteBackend) -> None:
    """AC2: patterns with ``tp_count < min_tp`` are filtered."""
    alert = _alert(alert_id="solo")
    await sqlite_storage.write_alert(alert)
    await sqlite_storage.append_feedback_event(
        alert_id="solo",
        feedback="tp",
        note="",
        origin="dashboard",
        submitted_at_ns=100,
    )
    result = await sqlite_storage.aggregate_tp_feedback(min_tp=3)
    assert result == ()


async def test_latest_verdict_per_alert_dedups(sqlite_storage: SqliteBackend) -> None:
    """AC2: TP→FP→TP sequence on the same alert counts as one TP."""
    alert = _alert(alert_id="flip")
    await sqlite_storage.write_alert(alert)
    # Three verdicts on the *same* alert_id: TP, FP, TP. Latest is TP.
    for ts, fb in ((100, "tp"), (200, "fp"), (300, "tp")):
        await sqlite_storage.append_feedback_event(
            alert_id="flip",
            feedback=fb,  # type: ignore[arg-type]
            note="",
            origin="dashboard",
            submitted_at_ns=ts,
        )
    # Plus two more alerts with clean TPs so the pattern crosses threshold.
    for i, a_id in enumerate(("clean-1", "clean-2"), start=1):
        await sqlite_storage.write_alert(_alert(alert_id=a_id))
        await sqlite_storage.append_feedback_event(
            alert_id=a_id,
            feedback="tp",
            note="",
            origin="dashboard",
            submitted_at_ns=400 + i,
        )
    result = await sqlite_storage.aggregate_tp_feedback(min_tp=3)
    assert len(result) == 1
    row = result[0]
    # 3 distinct alerts with latest-TP verdicts; the FP intermediate is
    # ignored. The flip-flop alert contributes once, not twice.
    assert row.tp_count == 3


async def test_latest_verdict_fp_excludes_alert(sqlite_storage: SqliteBackend) -> None:
    """AC2: TP→FP sequence excludes the alert (latest verdict is FP)."""
    alert = _alert(alert_id="became-fp")
    await sqlite_storage.write_alert(alert)
    for ts, fb in ((100, "tp"), (200, "fp")):
        await sqlite_storage.append_feedback_event(
            alert_id="became-fp",
            feedback=fb,  # type: ignore[arg-type]
            note="",
            origin="dashboard",
            submitted_at_ns=ts,
        )
    # Only one alert with latest TP → below threshold of 3.
    result = await sqlite_storage.aggregate_tp_feedback(min_tp=1)
    assert result == ()


async def test_multiple_patterns_ordered_tp_count_desc(
    sqlite_storage: SqliteBackend,
) -> None:
    """AC3: rows ordered ``tp_count DESC``."""
    # Pattern A: 5 TPs on entity_type=ip
    for i in range(5):
        a_id = f"a-{i}"
        await sqlite_storage.write_alert(_alert(alert_id=a_id, entity_type="ip"))
        await sqlite_storage.append_feedback_event(
            alert_id=a_id,
            feedback="tp",
            note="",
            origin="dashboard",
            submitted_at_ns=1_000 + i,
        )
    # Pattern B: 3 TPs on entity_type=host
    for i in range(3):
        b_id = f"b-{i}"
        await sqlite_storage.write_alert(_alert(alert_id=b_id, entity_type="host"))
        await sqlite_storage.append_feedback_event(
            alert_id=b_id,
            feedback="tp",
            note="",
            origin="dashboard",
            submitted_at_ns=2_000 + i,
        )
    result = await sqlite_storage.aggregate_tp_feedback(min_tp=3)
    assert [r.pattern_key for r in result] == [
        "ml:hst-anomaly:ip",
        "ml:hst-anomaly:host",
    ]
    assert [r.tp_count for r in result] == [5, 3]


async def test_window_ns_clipping(sqlite_storage: SqliteBackend) -> None:
    """AC2: ``window_ns`` filters out feedback older than the window.

    Three TPs total. Two are inside the 1000ns window; one is older.
    Threshold is 2 → only the in-window slice counts → pattern eligible
    with ``tp_count=2``.
    """
    for i in range(3):
        a_id = f"a-{i}"
        await sqlite_storage.write_alert(_alert(alert_id=a_id))
    # Two recent TPs (ts 9_500 and 9_900), one ancient (ts 100).
    await sqlite_storage.append_feedback_event(
        alert_id="a-0",
        feedback="tp",
        note="",
        origin="dashboard",
        submitted_at_ns=100,
    )
    await sqlite_storage.append_feedback_event(
        alert_id="a-1",
        feedback="tp",
        note="",
        origin="dashboard",
        submitted_at_ns=9_500,
    )
    await sqlite_storage.append_feedback_event(
        alert_id="a-2",
        feedback="tp",
        note="",
        origin="dashboard",
        submitted_at_ns=9_900,
    )
    # window_ns=1_000, now_ns=10_000 → events >= 9_000 only.
    result = await sqlite_storage.aggregate_tp_feedback(min_tp=2, window_ns=1_000, now_ns=10_000)
    assert len(result) == 1
    assert result[0].tp_count == 2


async def test_contributing_alert_ids_capped_at_16(
    sqlite_storage: SqliteBackend,
) -> None:
    """AC2: ``contributing_alert_ids`` is capped at 16 newest-first."""
    for i in range(20):
        a_id = f"a-{i:02d}"
        await sqlite_storage.write_alert(_alert(alert_id=a_id))
        await sqlite_storage.append_feedback_event(
            alert_id=a_id,
            feedback="tp",
            note="",
            origin="dashboard",
            submitted_at_ns=1_000 + i,
        )
    result = await sqlite_storage.aggregate_tp_feedback(min_tp=3)
    assert len(result) == 1
    assert len(result[0].contributing_alert_ids) == 16
    # Newest first: a-19, a-18, ..., a-04
    assert result[0].contributing_alert_ids[0] == "a-19"
    assert result[0].contributing_alert_ids[-1] == "a-04"


async def test_limit_truncates_returned_rows(sqlite_storage: SqliteBackend) -> None:
    """AC2: ``limit`` parameter truncates the returned rows."""
    for i in range(3):
        a_id = f"a-{i}"
        await sqlite_storage.write_alert(_alert(alert_id=a_id, entity_type="ip"))
        await sqlite_storage.append_feedback_event(
            alert_id=a_id,
            feedback="tp",
            note="",
            origin="dashboard",
            submitted_at_ns=1_000 + i,
        )
    for i in range(3):
        b_id = f"b-{i}"
        await sqlite_storage.write_alert(_alert(alert_id=b_id, entity_type="host"))
        await sqlite_storage.append_feedback_event(
            alert_id=b_id,
            feedback="tp",
            note="",
            origin="dashboard",
            submitted_at_ns=2_000 + i,
        )
    result = await sqlite_storage.aggregate_tp_feedback(min_tp=3, limit=1)
    assert len(result) == 1


async def test_missing_alert_row_excluded(sqlite_storage: SqliteBackend) -> None:
    """AC2: feedback rows referencing a deleted alert are silently dropped.

    The aggregator JOINs through the alerts table, so a feedback row
    pointing at an ``alert_id`` that no longer exists in ``alerts`` (e.g.
    after a cleanup job) does not surface a pattern key.
    """
    await sqlite_storage.append_feedback_event(
        alert_id="ghost",
        feedback="tp",
        note="",
        origin="dashboard",
        submitted_at_ns=100,
    )
    result = await sqlite_storage.aggregate_tp_feedback(min_tp=1)
    assert result == ()
