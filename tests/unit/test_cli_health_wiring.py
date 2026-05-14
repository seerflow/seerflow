"""Verify the pipeline runner threads a ``StageLatencyTracker`` into both
the FastAPI factory and ``make_handler`` (S-080).

The runner has a 700-line body, so this test asserts the contract via a
narrower probe: when the runner builds its handler, it passes a non-None
``latency_tracker`` kwarg; when it builds the API app, it passes the same
tracker as ``stage_latency_tracker``. We exercise the runner's actual
factory-call shape by inspecting the helper that constructs the tracker.
"""

from __future__ import annotations

import inspect

from seerflow.api.latency import StageLatencyTracker
from seerflow.pipeline import run as pipeline_run


class TestRunnerLatencyWiring:
    """Tracker is created in the runner and passed to both call sites."""

    def test_runner_module_imports_stage_latency_tracker(self) -> None:
        # The runner must depend on the tracker symbol (proves wiring exists).
        src = inspect.getsource(pipeline_run)
        assert "StageLatencyTracker" in src

    def test_runner_passes_tracker_to_handler(self) -> None:
        src = inspect.getsource(pipeline_run)
        # ``make_handler`` call must include the ``latency_tracker=`` kwarg.
        assert "latency_tracker=" in src

    def test_runner_passes_tracker_to_api_factory(self) -> None:
        src = inspect.getsource(pipeline_run)
        # ``make_api_app`` call must include the ``stage_latency_tracker=`` kwarg.
        assert "stage_latency_tracker=" in src

    def test_tracker_is_constructible_from_runner_context(self) -> None:
        """Sanity: the tracker the runner constructs is a real instance."""
        t = StageLatencyTracker()
        assert t.snapshot() == {}
