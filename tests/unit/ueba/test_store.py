"""Unit tests for BaselineStore."""

from __future__ import annotations

import uuid as _uuid

import pytest

from seerflow.models.event import SeerflowEvent
from seerflow.ueba.baseline import UEBAParams
from seerflow.ueba.store import BaselineStore


def _params() -> UEBAParams:
    return UEBAParams(
        alpha=0.5,
        source_ip_cap=8,
        template_top_k=8,
        warmup_days=7,
        warmup_min_events=50,
    )


def _mk_event(entity_uuid: str, ts_ns: int, ip: str = "10.0.0.1") -> SeerflowEvent:
    return SeerflowEvent(
        event_id=_uuid.uuid4(),
        timestamp_ns=ts_ns,
        observed_ns=ts_ns,
        otel_severity=9,
        related_ips=(ip,),
        entity_refs=(entity_uuid,),
        template_id=1,
    )


@pytest.mark.unit
def test_snapshot_and_learn_returns_none_when_no_entity_refs() -> None:
    store = BaselineStore(params=_params(), max_entities=4)
    e = SeerflowEvent(
        event_id=_uuid.uuid4(),
        timestamp_ns=1,
        observed_ns=1,
        otel_severity=9,
        entity_refs=(),
    )
    assert store.snapshot_and_learn(e, entity_types=()) is None


@pytest.mark.unit
def test_snapshot_and_learn_first_event_returns_none_but_creates_baseline() -> None:
    store = BaselineStore(params=_params(), max_entities=4)
    e = _mk_event("u1", ts_ns=1_000)
    snap = store.snapshot_and_learn(e, entity_types=("user",))
    assert snap is None  # no prior baseline to return
    after = store.get("u1")
    assert after is not None
    assert after.event_count == 1


@pytest.mark.unit
def test_snapshot_returns_pre_update_state_on_second_event() -> None:
    store = BaselineStore(params=_params(), max_entities=4)
    store.snapshot_and_learn(_mk_event("u1", 1_000), entity_types=("user",))
    snap = store.snapshot_and_learn(_mk_event("u1", 2_000), entity_types=("user",))
    assert snap is not None
    assert snap.event_count == 1  # the PRE-second-event count
    after = store.get("u1")
    assert after is not None
    assert after.event_count == 2  # post-update count


@pytest.mark.unit
def test_get_does_not_promote_lru() -> None:
    store = BaselineStore(params=_params(), max_entities=2)
    store.snapshot_and_learn(_mk_event("u1", 1), entity_types=("user",))
    store.snapshot_and_learn(_mk_event("u2", 2), entity_types=("user",))
    store.get("u1")  # does NOT promote
    store.snapshot_and_learn(_mk_event("u3", 3), entity_types=("user",))
    # u1 is oldest-updated and should have been evicted.
    assert store.get("u1") is None
    assert store.get("u2") is not None
    assert store.get("u3") is not None


@pytest.mark.unit
def test_learn_promotes_lru() -> None:
    store = BaselineStore(params=_params(), max_entities=2)
    store.snapshot_and_learn(_mk_event("u1", 1), entity_types=("user",))
    store.snapshot_and_learn(_mk_event("u2", 2), entity_types=("user",))
    store.snapshot_and_learn(_mk_event("u1", 3), entity_types=("user",))  # refresh u1
    store.snapshot_and_learn(_mk_event("u3", 4), entity_types=("user",))
    # u2 was the oldest-updated this time.
    assert store.get("u1") is not None
    assert store.get("u2") is None
    assert store.get("u3") is not None


from pathlib import Path  # noqa: E402

from seerflow.config import StorageConfig  # noqa: E402
from seerflow.storage.sqlite import SqliteBackend  # noqa: E402


async def test_store_flush_and_restore_round_trip(tmp_path: Path) -> None:
    cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "t.db"))
    backend = await SqliteBackend.connect(cfg)
    try:
        a = BaselineStore(params=_params(), max_entities=4)
        a.snapshot_and_learn(_mk_event("u1", 1), entity_types=("user",))
        a.snapshot_and_learn(_mk_event("u2", 2), entity_types=("user",))
        await a.flush(backend)

        b = BaselineStore(params=_params(), max_entities=4)
        restored = await b.restore(backend)
        assert restored == 2
        assert b.get("u1") is not None
        assert b.get("u2") is not None
        # LRU order preserved: u1 older than u2.
        assert list(b._baselines.keys()) == ["u1", "u2"]
    finally:
        await backend.close()


async def test_restore_missing_key_is_noop(tmp_path: Path) -> None:
    cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "t.db"))
    backend = await SqliteBackend.connect(cfg)
    try:
        store = BaselineStore(params=_params(), max_entities=4)
        restored = await store.restore(backend)
        assert restored == 0
        assert len(store) == 0
    finally:
        await backend.close()
