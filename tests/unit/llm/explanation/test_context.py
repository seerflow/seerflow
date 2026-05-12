"""Unit tests for the entity baseline context loader (S-071, Task 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.llm.explanation.context import (
    EntityBaselineContext,
    load_entity_baseline_context,
)
from seerflow.ueba.baseline import EntityBaseline

if TYPE_CHECKING:
    from seerflow.ueba.baseline import EntityType


class _FakeBaselineStore:
    """Minimal in-memory baseline store for tests."""

    def __init__(self, baseline: EntityBaseline | None = None) -> None:
        self._baseline = baseline

    def get(self, entity_uuid: str) -> EntityBaseline | None:
        return self._baseline


def _baseline(entity_uuid: str = "u-1") -> EntityBaseline:
    hours = tuple(0 if i not in (9, 12, 14) else (10 if i == 14 else 5) for i in range(24))
    entity_type: EntityType = "user"
    return EntityBaseline(
        entity_uuid=entity_uuid,
        entity_type=entity_type,
        first_seen_ns=1_700_000_000_000_000_000,
        last_seen_ns=1_700_000_500_000_000_000,
        event_count=200,
        warmup_complete=True,
        hours=hours,
        source_ips=(("10.0.0.1", 1_700_000_500_000_000_000),),
        volume_ema_min=12.34,
        volume_ema_hour=410.0,
        volume_last_ns=1_700_000_500_000_000_000,
        templates=(),
    )


@pytest.mark.unit
def test_loader_returns_none_summary_when_store_is_none() -> None:
    context = load_entity_baseline_context(
        entity_uuid="u-1",
        entity_value="alice",
        entity_type="user",
        baseline_store=None,
    )
    assert isinstance(context, EntityBaselineContext)
    assert context.baseline_summary is None
    assert context.entity_value == "alice"


@pytest.mark.unit
def test_loader_returns_none_summary_when_store_misses() -> None:
    store = _FakeBaselineStore(baseline=None)
    context = load_entity_baseline_context(
        entity_uuid="u-1",
        entity_value="alice",
        entity_type="user",
        baseline_store=store,  # type: ignore[arg-type]
    )
    assert context.baseline_summary is None


@pytest.mark.unit
def test_loader_builds_summary_when_baseline_present() -> None:
    store = _FakeBaselineStore(baseline=_baseline())
    context = load_entity_baseline_context(
        entity_uuid="u-1",
        entity_value="alice",
        entity_type="user",
        baseline_store=store,  # type: ignore[arg-type]
    )
    assert context.baseline_summary is not None
    summary = context.baseline_summary
    assert "events=200" in summary
    # Top hour bucket (14) appears first.
    assert "14h" in summary
    # ISO timestamp with timezone.
    assert "T" in summary
    # warmup_complete=True
    assert "warmup_complete=True" in summary


@pytest.mark.unit
def test_loader_handles_empty_hour_histogram() -> None:
    bl = _baseline()
    # Replace hours with all zeros — simulate a fresh entity.
    empty_hours = tuple([0] * 24)
    bl_zero = EntityBaseline(
        entity_uuid=bl.entity_uuid,
        entity_type=bl.entity_type,
        first_seen_ns=bl.first_seen_ns,
        last_seen_ns=bl.last_seen_ns,
        event_count=0,
        warmup_complete=False,
        hours=empty_hours,
        source_ips=bl.source_ips,
        volume_ema_min=0.0,
        volume_ema_hour=0.0,
        volume_last_ns=bl.volume_last_ns,
        templates=bl.templates,
    )
    store = _FakeBaselineStore(baseline=bl_zero)
    context = load_entity_baseline_context(
        entity_uuid="u-1",
        entity_value="alice",
        entity_type="user",
        baseline_store=store,  # type: ignore[arg-type]
    )
    assert context.baseline_summary is not None
    assert "busiest_hours_utc=n/a" in context.baseline_summary
