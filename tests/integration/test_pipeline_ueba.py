"""End-to-end: pipeline event → BaselineStore → flush → restore → get."""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING

from seerflow.config import StorageConfig
from seerflow.models.event import SeerflowEvent
from seerflow.storage.sqlite import SqliteBackend
from seerflow.ueba.baseline import UEBAParams
from seerflow.ueba.store import BaselineStore

if TYPE_CHECKING:
    from pathlib import Path


UUID_OK = "11111111-1111-5111-8111-111111111111"


async def test_end_to_end_persistence_cycle(tmp_path: Path) -> None:
    cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "t.db"))
    backend = await SqliteBackend.connect(cfg)
    try:
        params = UEBAParams(
            alpha=0.05,
            source_ip_cap=8,
            template_top_k=8,
            warmup_days=1,
            warmup_min_events=3,
        )
        store = BaselineStore(params=params, max_entities=100)
        for i in range(4):
            event = SeerflowEvent(
                event_id=_uuid.uuid4(),
                timestamp_ns=i * 86_400 * 1_000_000_000,
                observed_ns=i * 86_400 * 1_000_000_000,
                otel_severity=9,
                related_ips=("10.0.0.1",),
                entity_refs=(UUID_OK,),
                template_id=1,
            )
            store.snapshot_and_learn(event, entity_types=("ip",))

        before = store.get(UUID_OK)
        assert before is not None
        assert before.warmup_complete is True

        await store.flush(backend)

        # Fresh store — simulate restart.
        store2 = BaselineStore(params=params, max_entities=100)
        restored = await store2.restore(backend)
        assert restored == 1
        after = store2.get(UUID_OK)
        assert after == before
    finally:
        await backend.close()
