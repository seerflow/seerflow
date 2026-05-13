"""Unit tests for ``seerflow.llm.rule_suggestion.aggregator``.

Covers AC2/AC3 with an in-memory fake ``AlertStore`` that implements only
the ``aggregate_tp_feedback`` method. The real SQLite + PostgreSQL
implementations are exercised in storage-specific tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from seerflow.llm.rule_suggestion.aggregator import (
    PatternFeedbackRow,
    count_pattern_tps,
)


@dataclass
class _FakeAlertStore:
    """Minimal fake satisfying the slice of ``AlertStore`` we exercise."""

    rows: tuple[PatternFeedbackRow, ...] = ()
    last_call: dict[str, object] | None = None

    async def aggregate_tp_feedback(
        self,
        *,
        min_tp: int,
        window_ns: int | None = None,
        now_ns: int | None = None,
        limit: int = 50_000,
    ) -> tuple[PatternFeedbackRow, ...]:
        # Mimic real storage filtering — return only rows meeting min_tp.
        # ``window_ns`` and ``now_ns`` semantics live in the SQL layer;
        # the unit test asserts the wrapper forwards them unchanged.
        self.last_call = {
            "min_tp": min_tp,
            "window_ns": window_ns,
            "now_ns": now_ns,
            "limit": limit,
        }
        return tuple(r for r in self.rows if r.tp_count >= min_tp)[:limit]


def _row(
    pattern_key: str,
    tp_count: int,
    most_recent_tp_ns: int,
    contributing_alert_ids: tuple[str, ...] = (),
) -> PatternFeedbackRow:
    return PatternFeedbackRow(
        pattern_key=pattern_key,
        tp_count=tp_count,
        most_recent_tp_ns=most_recent_tp_ns,
        contributing_alert_ids=contributing_alert_ids,
    )


class TestCountPatternTps:
    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_tuple(self) -> None:
        """AC2: empty store yields no rows."""
        store = _FakeAlertStore()
        result = await count_pattern_tps(store, min_tp=3)
        assert result == ()

    @pytest.mark.asyncio
    async def test_below_threshold_filtered(self) -> None:
        """AC2: patterns with ``tp_count < min_tp`` are filtered out."""
        store = _FakeAlertStore(
            rows=(_row("ml:hst-anomaly:ip", tp_count=2, most_recent_tp_ns=100),)
        )
        result = await count_pattern_tps(store, min_tp=3)
        assert result == ()

    @pytest.mark.asyncio
    async def test_meets_threshold_returned(self) -> None:
        """AC2: ``tp_count >= min_tp`` patterns are returned."""
        store = _FakeAlertStore(
            rows=(
                _row(
                    "ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=300,
                    contributing_alert_ids=("a3", "a2", "a1"),
                ),
            )
        )
        result = await count_pattern_tps(store, min_tp=3)
        assert len(result) == 1
        assert result[0].pattern_key == "ml:hst-anomaly:ip"
        assert result[0].tp_count == 3
        assert result[0].contributing_alert_ids == ("a3", "a2", "a1")

    @pytest.mark.asyncio
    async def test_multiple_patterns_returned(self) -> None:
        """AC3: multiple eligible patterns surface."""
        store = _FakeAlertStore(
            rows=(
                _row("ml:hst-anomaly:ip", tp_count=5, most_recent_tp_ns=500),
                _row("ml:hst-anomaly:host", tp_count=3, most_recent_tp_ns=300),
            )
        )
        result = await count_pattern_tps(store, min_tp=3)
        assert len(result) == 2
        keys = {r.pattern_key for r in result}
        assert keys == {"ml:hst-anomaly:ip", "ml:hst-anomaly:host"}

    @pytest.mark.asyncio
    async def test_window_ns_passed_through(self) -> None:
        """AC2: ``window_ns`` is forwarded to the storage layer."""
        store = _FakeAlertStore()
        await count_pattern_tps(
            store,
            min_tp=3,
            window_ns=86_400_000_000_000,
            now_ns=1_700_000_000_000_000_000,
        )
        assert store.last_call["window_ns"] == 86_400_000_000_000
        assert store.last_call["now_ns"] == 1_700_000_000_000_000_000

    @pytest.mark.asyncio
    async def test_contributing_alert_ids_capped_at_16(self) -> None:
        """AC2: aggregator caps ``contributing_alert_ids`` at 16 newest-first.

        Storage may return more than 16; the wrapper clips defensively so
        downstream consumers (prompt builder) have a bounded budget.
        """
        ids = tuple(f"alert-{i}" for i in range(20))  # 20 IDs, newest first
        store = _FakeAlertStore(
            rows=(
                _row(
                    "ml:hst-anomaly:ip",
                    tp_count=20,
                    most_recent_tp_ns=2_000,
                    contributing_alert_ids=ids,
                ),
            )
        )
        result = await count_pattern_tps(store, min_tp=3)
        assert len(result) == 1
        assert len(result[0].contributing_alert_ids) == 16
        assert result[0].contributing_alert_ids == ids[:16]

    @pytest.mark.asyncio
    async def test_default_min_tp_from_config(self) -> None:
        """AC2: the default ``min_tp`` argument matches FR-066 (3)."""
        # Two TPs should not pass the default threshold.
        store = _FakeAlertStore(
            rows=(_row("ml:hst-anomaly:ip", tp_count=2, most_recent_tp_ns=100),)
        )
        result = await count_pattern_tps(store)
        assert result == ()

    @pytest.mark.asyncio
    async def test_limit_forwarded(self) -> None:
        """AC2: ``limit`` is forwarded to the storage layer."""
        store = _FakeAlertStore()
        await count_pattern_tps(store, min_tp=3, limit=10)
        assert store.last_call["limit"] == 10


class TestPatternFeedbackRow:
    def test_frozen(self) -> None:
        """``PatternFeedbackRow`` is immutable."""
        row = _row("ml:x:ip", tp_count=3, most_recent_tp_ns=100)
        with pytest.raises(AttributeError):
            row.tp_count = 5  # type: ignore[misc]

    def test_default_contributing_alert_ids(self) -> None:
        """``contributing_alert_ids`` defaults to empty tuple."""
        row = PatternFeedbackRow(
            pattern_key="ml:x:ip",
            tp_count=3,
            most_recent_tp_ns=100,
        )
        assert row.contributing_alert_ids == ()
