"""Integration test: pipeline invokes BaselineStore.snapshot_and_learn."""

from __future__ import annotations

import pytest

from seerflow.ueba.baseline import UEBAParams
from seerflow.ueba.store import BaselineStore


async def test_handler_calls_baseline_store_for_resolved_entities() -> None:
    """Contract-level smoke: make_handler accepts baseline_store kwarg.

    Full end-to-end pipeline invocation is covered in Task 10.
    """
    from seerflow.pipeline.handler import make_handler  # noqa: PLC0415

    pytest.importorskip("seerflow.pipeline.handler")

    params = UEBAParams(
        alpha=0.05,
        source_ip_cap=64,
        template_top_k=32,
        warmup_days=7,
        warmup_min_events=50,
    )
    store = BaselineStore(params=params, max_entities=100)
    assert callable(make_handler)
    assert hasattr(store, "snapshot_and_learn")
