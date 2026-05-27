"""Regression guard (S-305 / FR-073 AC6): the LANL harness must drive the
full ``assemble_handler`` wiring, never silently revert to correlation-only.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"


def test_validator_source_has_no_direct_correlation_engine() -> None:
    """AC1/AC6: validator.py must not construct CorrelationEngine itself."""
    from seerflow.lanl import validator

    src = inspect.getsource(validator)
    assert "CorrelationEngine(" not in src
    assert "assemble_handler" in src


async def test_run_validation_invokes_assemble_handler() -> None:
    """assemble_handler must be called and the run must process events."""
    from seerflow.lanl import validator
    from seerflow.pipeline.assembly import assemble_handler as real_assemble

    called: dict[str, bool] = {}

    async def spy(config, storage, **kwargs):
        # Forward all keyword args (capture_sink, ws_manager, and the S-334
        # ``clock_ns`` replay-clock injection) so the spied run is wired
        # identically to the real harness.
        called["hit"] = True
        return await real_assemble(config, storage, **kwargs)

    with patch("seerflow.pipeline.assembly.assemble_handler", side_effect=spy):
        result = await validator.run_validation_async(FIXTURES_DIR)

    assert called.get("hit") is True
    assert result.total_events_processed > 0


def test_full_stack_run_reports_per_family_and_scope_label() -> None:
    """The sync entry point produces per-family metrics + an honest label."""
    from seerflow.lanl.validator import run_validation

    result = run_validation(FIXTURES_DIR)
    assert isinstance(result.per_family, dict)
    assert "synthetic LANL subset" in result.scope_label
    assert 0.0 <= result.precision <= 1.0
    assert 0.0 <= result.recall <= 1.0
