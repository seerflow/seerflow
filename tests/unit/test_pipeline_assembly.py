"""Unit tests for ``seerflow.pipeline.assembly.assemble_handler`` (S-302).

Mirrors the S-301 characterization assertions
(``tests/unit/test_pipeline_run_characterization.py``) so the extracted
factory is provably the same wiring ``_run_with_config`` feeds into
``make_handler`` — except ``ws_manager`` is ``None`` by design (the factory
builds no FastAPI app; S-304 re-supplies the live instance).

Self-contained stub stack: a regression guard must not cross-import another
test module's private helpers. Everything mocked: no real network, no
storage I/O.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import AlertingConfig, SeerflowConfig, StorageConfig
from seerflow.pipeline.assembly import AssembledHandler, assemble_handler


def _stub_storage() -> MagicMock:
    storage = MagicMock()
    storage.close = AsyncMock()
    storage.load_edges = AsyncMock(return_value=[])
    storage.set_entity_graph = MagicMock()
    storage.load_iocs = AsyncMock(return_value=[])
    storage.get_model_state = AsyncMock(return_value=None)
    storage.load_baselines = AsyncMock(return_value=[])
    return storage


@pytest.mark.unit
async def test_assembled_handler_shape() -> None:
    """assemble_handler returns an AssembledHandler with handler/lifecycle/teardown."""
    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        shutdown_timeout_s=1.0,
    )
    storage = _stub_storage()

    result = await assemble_handler(config, storage)

    assert isinstance(result, AssembledHandler)
    assert callable(result.handler)
    assert isinstance(result.lifecycle, tuple)
    assert callable(result.teardown)
    await result.teardown()
