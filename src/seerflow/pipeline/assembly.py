"""Full-stack detection handler assembly (S-302, FR-069).

A single shared pure async factory that builds the exact engine wiring
``pipeline/run.py::_run_with_config`` feeds into ``make_handler`` today —
NO receivers (``build_pipeline``), NO FastAPI/uvicorn, NO LLM (API-only).

This makes live ``seerflow start`` ≡ ``seerflow analyze`` ≡ the LANL
benchmark wire detection identically by construction (NFR-013/017). The
behaviour-preserving refactor of ``_run_with_config`` to consume this
factory is S-304, guarded by ``tests/unit/test_pipeline_run_characterization.py``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from seerflow.config import SeerflowConfig
    from seerflow.receivers.base import RawEvent
    from seerflow.storage.factory import StorageBackend


@dataclass(frozen=True, slots=True)
class AssembledHandler:
    """Result of :func:`assemble_handler`.

    - ``handler``     — the ``make_handler(...)`` event closure.
    - ``lifecycle``   — background ``asyncio.Task``s the factory started
                         (rule reloader, TAXII loops, dispatcher/sink runs).
    - ``teardown``    — idempotent async stop-and-await for owned resources;
                         does NOT close ``storage`` (caller-owned) or touch
                         uvicorn (none built).
    - ``capture_sink`` — passthrough seam for S-303 (analyze/benchmark);
                         accepted but not yet wired into ``make_handler``.
    """

    handler: Callable[[RawEvent], Awaitable[None]]
    lifecycle: tuple[asyncio.Task[Any], ...]
    teardown: Callable[[], Awaitable[None]]
    capture_sink: object | None


async def assemble_handler(
    config: SeerflowConfig,
    storage: StorageBackend,
    *,
    capture_sink: object | None = None,
) -> AssembledHandler:
    """Build the full-stack ``make_handler(...)`` wiring (no receivers/API)."""

    async def _noop_teardown() -> None:
        return None

    async def _placeholder(_event: RawEvent) -> None:  # pragma: no cover - replaced in Task 3+
        return None

    return AssembledHandler(
        handler=_placeholder,
        lifecycle=(),
        teardown=_noop_teardown,
        capture_sink=capture_sink,
    )
