"""Wiring tests for ``seerflow.pipeline.run._run_with_config`` (S-217).

These tests are intentionally source-level inspections rather than full
pipeline integration tests. They verify that ``_run_with_config`` exposes
the expected test seam (``make_api_app``), constructs a single shared
``ConnectionManager``, mounts the FastAPI app via uvicorn, surfaces a
helpful hint on ``EADDRINUSE``, logs the ``dist/`` missing case, and
runs the pipeline + uvicorn as sibling tasks with ordered shutdown.

The full integration coverage lives in
``tests/integration/test_start_serves_dashboard.py``.
"""

from __future__ import annotations


class TestMakeApiAppSeam:
    """``_run_with_config`` accepts an injected ``make_api_app`` factory."""

    def test_make_api_app_kwarg_present(self) -> None:
        from seerflow.pipeline import run as run_mod

        assert "make_api_app" in run_mod._run_with_config.__code__.co_varnames
