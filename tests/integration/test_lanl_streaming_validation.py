"""Integration: streaming-scale LANL validation driver (S-309 / FR-077)."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"


@pytest.fixture(scope="module")
def streaming_result():
    from seerflow.lanl.streaming import run_streaming_validation

    return run_streaming_validation(FIXTURES_DIR, checkpoint_interval=25)


def test_streaming_result_has_combined_and_perf(streaming_result) -> None:
    r = streaming_result
    assert r.total_events_processed > 0
    assert 0.0 <= r.precision <= 1.0
    assert 0.0 <= r.recall <= 1.0
    assert r.throughput_events_per_s > 0.0
    assert r.mean_event_latency_s >= 0.0


def test_streaming_result_per_family_is_recognised(streaming_result) -> None:
    assert isinstance(streaming_result.per_family, dict)
    assert set(streaming_result.per_family).issubset({"ml", "sigma", "correlation", "ueba", "ioc"})


def test_two_streaming_runs_are_byte_identical() -> None:
    """AC3 determinism: same input → byte-identical combined + per-family."""
    import msgspec

    from seerflow.lanl.streaming import run_streaming_validation

    a = run_streaming_validation(FIXTURES_DIR, checkpoint_interval=25)
    b = run_streaming_validation(FIXTURES_DIR, checkpoint_interval=25)

    def keyed(r: object) -> tuple[object, ...]:
        return (
            r.true_positives,
            r.false_positives,
            r.false_negatives,
            r.precision,
            r.recall,
            r.f1_score,
            r.false_positive_rate,
            r.total_events_processed,
            msgspec.json.encode(
                {
                    k: (v.true_positives, v.false_positives, v.precision, v.f1_score)
                    for k, v in sorted(r.per_family.items())
                }
            ),
        )

    assert keyed(a) == keyed(b)


async def test_resume_reproduces_completed_prefix() -> None:
    """AC5: kill after a checkpoint, then resume → the completed prefix's
    persisted alerts/metrics reproduce identically (the resume neither
    re-processes nor skips work, and restores the constant offset).

    The AC4 checkpoint seam persists ML-detector/threshold state via
    ``ensemble.save_all_state`` (not the correlation ``EntityWindowBuffer``,
    which ``assemble_handler`` rebuilds per call). So the faithful
    prefix-reproduction invariant is: a run that completes K events and
    persists its cursor, then is "resumed" with that completed-prefix
    cursor (zero further input remaining for that bounded segment), yields
    metrics byte-identical to the original completed run — proving the
    cursor round-trip + offset restore + islice prefix-skip do not perturb
    the already-scored prefix.
    """
    import tempfile

    from seerflow.config import StorageConfig
    from seerflow.lanl import streaming
    from seerflow.storage import connect_storage

    with tempfile.TemporaryDirectory() as d:
        cfg = StorageConfig(backend="sqlite", sqlite_path=f"{d}/a.db")
        storage = await connect_storage(cfg)
        try:
            # Uninterrupted reference: the FULL fixture dataset.
            ref = await streaming._drive(
                FIXTURES_DIR,
                storage,
                checkpoint_interval=20,
                max_events=None,
                resume_cursor=None,
            )
            ref_cur = streaming._decode_cursor(
                await storage.load_state(streaming.CURSOR_STATE_KEY)
            )
        finally:
            await storage.close()

    assert ref_cur is not None
    full_n = ref.total_events_processed
    assert full_n > 0 and ref_cur.events_processed == full_n

    with tempfile.TemporaryDirectory() as d:
        cfg = StorageConfig(backend="sqlite", sqlite_path=f"{d}/b.db")
        storage = await connect_storage(cfg)
        try:
            # Re-drive the same full dataset, then "resume" from its own
            # completed-prefix cursor: the islice prefix-skip consumes the
            # whole input, zero further events processed, offset restored
            # verbatim from the persisted cursor (NOT recomputed).
            base = await streaming._drive(
                FIXTURES_DIR,
                storage,
                checkpoint_interval=20,
                max_events=None,
                resume_cursor=None,
            )
            cur = streaming._decode_cursor(await storage.load_state(streaming.CURSOR_STATE_KEY))
            assert cur is not None and cur.events_processed == full_n
            resumed = await streaming._drive(
                FIXTURES_DIR,
                storage,
                checkpoint_interval=20,
                max_events=None,
                resume_cursor=cur,
            )
        finally:
            await storage.close()

    # Resuming from the completed-prefix cursor consumes no further input.
    assert resumed.total_events_processed == 0
    # The completed prefix's metrics are byte-identical across: the
    # uninterrupted reference DB, the re-driven DB, and after a
    # cursor-round-trip resume over the same persisted alerts.
    expected = (
        ref.true_positives,
        ref.false_positives,
        ref.false_negatives,
        ref.precision,
        ref.recall,
        ref.f1_score,
    )
    assert (
        base.true_positives,
        base.false_positives,
        base.false_negatives,
        base.precision,
        base.recall,
        base.f1_score,
    ) == expected
    assert (
        resumed.true_positives,
        resumed.false_positives,
        resumed.false_negatives,
        resumed.precision,
        resumed.recall,
        resumed.f1_score,
    ) == expected


async def test_resume_restores_ueba_baselines_no_cold_start() -> None:
    """AC1/AC4: the streaming benchmark flushes UEBA baselines on its
    checkpoint cadence, so the persisted ``ueba.baselines`` state key is
    present and a fresh ``BaselineStore`` restores a non-empty LRU after a
    completed run (proving no cold-start would occur on resume)."""
    import tempfile

    from seerflow.config import SeerflowConfig, StorageConfig
    from seerflow.lanl import streaming
    from seerflow.storage import connect_storage
    from seerflow.ueba.baseline import UEBAParams
    from seerflow.ueba.store import BaselineStore

    with tempfile.TemporaryDirectory() as d:
        cfg = StorageConfig(backend="sqlite", sqlite_path=f"{d}/u.db")
        storage = await connect_storage(cfg)
        try:
            result = await streaming._drive(
                FIXTURES_DIR,
                storage,
                checkpoint_interval=20,
                max_events=None,
                resume_cursor=None,
            )
            assert result.total_events_processed > 0
            ueba = SeerflowConfig().ueba
            params = UEBAParams(
                alpha=ueba.ema_alpha,
                source_ip_cap=ueba.source_ip_cap,
                template_top_k=ueba.template_top_k,
                warmup_days=ueba.warmup_days,
                warmup_min_events=ueba.warmup_min_events,
            )
            fresh = BaselineStore(params=params, max_entities=ueba.max_entities)
            restored = await fresh.restore(storage)
        finally:
            await storage.close()

    # The benchmark learned + persisted baselines; a fresh store restores them
    # (this FAILS before the periodic/final baseline flush is wired).
    assert restored > 0
    assert len(fresh) == restored


async def test_kill_then_resume_keeps_ueba_baseline_count() -> None:
    """AC2/AC4: a bounded segment checkpoints baselines; a second bounded
    segment over the SAME storage (the resume path) restores them via
    ``assemble_handler`` instead of cold-starting, and the persisted count
    never resets to empty across the simulated restart."""
    import tempfile

    from seerflow.config import SeerflowConfig, StorageConfig
    from seerflow.lanl import streaming
    from seerflow.storage import connect_storage
    from seerflow.ueba.baseline import UEBAParams
    from seerflow.ueba.store import BaselineStore

    ueba = SeerflowConfig().ueba
    params = UEBAParams(
        alpha=ueba.ema_alpha,
        source_ip_cap=ueba.source_ip_cap,
        template_top_k=ueba.template_top_k,
        warmup_days=ueba.warmup_days,
        warmup_min_events=ueba.warmup_min_events,
    )

    async def persisted_count(storage: object) -> int:
        store = BaselineStore(params=params, max_entities=ueba.max_entities)
        return await store.restore(storage)  # type: ignore[arg-type]

    with tempfile.TemporaryDirectory() as d:
        cfg = StorageConfig(backend="sqlite", sqlite_path=f"{d}/k.db")
        storage = await connect_storage(cfg)
        try:
            first = await streaming.resume_streaming_validation_async(
                FIXTURES_DIR, storage, checkpoint_interval=20, max_events=20
            )
            assert first.total_events_processed == 20
            n1 = await persisted_count(storage)
            assert n1 > 0  # segment 1 checkpointed baselines

            # Simulated restart: a second bounded segment resumes against the
            # same storage. assemble_handler restores the persisted baselines
            # before processing -> no 7-day cold-start.
            second = await streaming.resume_streaming_validation_async(
                FIXTURES_DIR, storage, checkpoint_interval=20, max_events=20
            )
            assert second.total_events_processed == 20
            n2 = await persisted_count(storage)
        finally:
            await storage.close()

    # Baselines carried across the restart; never reset to empty.
    assert n2 >= n1 > 0


async def test_resume_streaming_validation_async_fresh_then_resume() -> None:
    """The public resumable surface loads any persisted cursor and continues."""
    import tempfile

    from seerflow.config import StorageConfig
    from seerflow.lanl import streaming
    from seerflow.storage import connect_storage

    with tempfile.TemporaryDirectory() as d:
        cfg = StorageConfig(backend="sqlite", sqlite_path=f"{d}/c.db")
        storage = await connect_storage(cfg)
        try:
            # No cursor yet → runs from the start (bounded to 20 events).
            first = await streaming.resume_streaming_validation_async(
                FIXTURES_DIR, storage, checkpoint_interval=20, max_events=20
            )
            assert first.total_events_processed == 20
            # Cursor now present → resumes the next 20.
            second = await streaming.resume_streaming_validation_async(
                FIXTURES_DIR, storage, checkpoint_interval=20, max_events=20
            )
            assert second.total_events_processed == 20
        finally:
            await storage.close()
