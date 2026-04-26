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


class TestPortInUse:
    """``_run_with_config`` surfaces a clear hint when port is in use."""

    def test_helpful_message_appears_in_module_source(self) -> None:
        import inspect

        from seerflow.pipeline import run as run_mod

        src = inspect.getsource(run_mod)
        assert "EADDRINUSE" in src or "errno.EADDRINUSE" in src
        assert "dashboard_port" in src


class TestDistMissingHint:
    """``_run_with_config`` logs a hint when the React bundle is absent."""

    def test_hint_string_present_in_source(self) -> None:
        import inspect

        from seerflow.pipeline import run as run_mod

        src = inspect.getsource(run_mod._run_with_config)
        assert "npm run build" in src
        assert "Dashboard bundle missing" in src


class TestShutdownOrder:
    """Pipeline + uvicorn run as siblings; uvicorn stops before storage."""

    def test_finally_block_stops_server_before_storage_close(self) -> None:
        import inspect

        from seerflow.pipeline import run as run_mod

        src = inspect.getsource(run_mod._run_with_config)

        idx_should_exit = src.find("server.should_exit = True")
        # ``storage.close`` appears twice: once in the early build_pipeline
        # error path (start-up failure) and once in the cleanup finally
        # block. The shutdown ordering invariant only applies to the
        # cleanup-path occurrence — use the last index.
        idx_storage_close = src.rfind("await storage.close()")
        assert idx_should_exit != -1, "uvicorn shutdown signal missing"
        assert idx_storage_close != -1, "storage.close() missing"
        assert idx_should_exit < idx_storage_close, (
            "uvicorn must stop before storage.close()"
        )

    def test_uses_asyncio_wait_first_completed(self) -> None:
        import inspect

        from seerflow.pipeline import run as run_mod

        src = inspect.getsource(run_mod._run_with_config)
        assert "FIRST_COMPLETED" in src
        assert "pipeline_task" in src
