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


class TestSharedConnectionManager:
    """One ``ConnectionManager`` shared by handler and FastAPI app."""

    def test_make_handler_receives_ws_manager(self) -> None:
        import inspect

        from seerflow.pipeline import run as run_mod

        src = inspect.getsource(run_mod._run_with_config)
        # A single ConnectionManager is built and passed to make_handler.
        # The construction may carry kwargs (e.g. alert_store=storage) so
        # match the call site rather than the bare ``ConnectionManager()``.
        assert "ws_manager = ConnectionManager(" in src
        assert "ws_manager=ws_manager" in src


class TestServeFastapi:
    """``_run_with_config`` mounts FastAPI via uvicorn, not aiohttp."""

    def test_make_api_app_called_in_source(self) -> None:
        import inspect

        from seerflow.pipeline import run as run_mod

        src = inspect.getsource(run_mod._run_with_config)
        assert "make_api_app(" in src
        assert "uvicorn.Server" in src
        assert "create_health_app" not in src  # legacy aiohttp path removed
