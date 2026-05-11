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

from tests.helpers import function_source_text, module_source_text


class TestMakeApiAppSeam:
    """``_run_with_config`` accepts an injected ``make_api_app`` factory."""

    def test_make_api_app_kwarg_present(self) -> None:
        from seerflow.pipeline import run as run_mod

        assert "make_api_app" in run_mod._run_with_config.__code__.co_varnames


class TestDeriveLlmHealth:
    """``_derive_llm_health`` covers S-070's three-state surface."""

    def test_ready_when_backend_present(self) -> None:
        from seerflow.pipeline.run import _derive_llm_health

        assert _derive_llm_health(object(), "llama_cpp") == "ready"

    def test_disabled_when_no_backend_and_no_config(self) -> None:
        from seerflow.pipeline.run import _derive_llm_health

        assert _derive_llm_health(None, "") == "disabled"

    def test_degraded_when_no_backend_but_config_present(self) -> None:
        from seerflow.pipeline.run import _derive_llm_health

        assert _derive_llm_health(None, "llama_cpp") == "degraded"

    def test_ready_takes_precedence_over_config(self) -> None:
        # A constructed backend always wins, regardless of config string.
        from seerflow.pipeline.run import _derive_llm_health

        assert _derive_llm_health(object(), "") == "ready"


class TestSharedConnectionManager:
    """One ``ConnectionManager`` shared by handler and FastAPI app."""

    def test_make_handler_receives_ws_manager(self) -> None:
        import re

        from seerflow.pipeline import run as run_mod

        src = function_source_text(run_mod._run_with_config)
        # A single ConnectionManager is built and passed to make_handler.
        # The construction may carry kwargs (e.g. alert_store=storage); use a
        # whitespace-tolerant pattern so a future ruff format pass won't
        # silently break this assertion.
        # The shared ConnectionManager is built by ``create_api_app`` (via
        # ``_build_ws_manager``) and read back from ``app.state.ws_manager``;
        # the same instance is then passed to ``make_handler`` so frames
        # broadcast inside the pipeline reach the FastAPI WS route.
        assert "api_app.state.ws_manager" in src, (
            "expected `ws_manager` to be sourced from `api_app.state.ws_manager`"
        )
        assert re.search(r"ws_manager\s*=\s*ws_manager\b", src), (
            "expected `ws_manager=ws_manager` kwarg in make_handler call"
        )
        # And the factory must be called with ``ws_manager=None`` so it
        # builds the manager via ``_build_ws_manager`` (CSWSH-safe path).
        assert re.search(r"ws_manager\s*=\s*None\b", src), (
            "expected `ws_manager=None` in make_api_app call so the factory "
            "constructs a config-aware ConnectionManager via _build_ws_manager"
        )


class TestServeFastapi:
    """``_run_with_config`` mounts FastAPI via uvicorn, not aiohttp."""

    def test_make_api_app_called_in_source(self) -> None:
        from seerflow.pipeline import run as run_mod

        src = function_source_text(run_mod._run_with_config)
        assert "make_api_app(" in src
        assert "uvicorn.Server" in src
        assert "create_health_app" not in src  # legacy aiohttp path removed


class TestPortInUse:
    """``_run_with_config`` surfaces a clear hint when port is in use."""

    def test_helpful_message_appears_in_module_source(self) -> None:
        from seerflow.pipeline import run as run_mod

        src = module_source_text(run_mod)
        assert "EADDRINUSE" in src or "errno.EADDRINUSE" in src
        assert "dashboard_port" in src


class TestDistMissingHint:
    """``_run_with_config`` logs a hint when the React bundle is absent."""

    def test_hint_string_present_in_source(self) -> None:
        from seerflow.pipeline import run as run_mod

        src = function_source_text(run_mod._run_with_config)
        assert "npm run build" in src
        assert "Dashboard bundle missing" in src


class TestShutdownOrder:
    """Pipeline + uvicorn run as siblings; uvicorn stops before storage."""

    def test_finally_block_stops_server_before_storage_close(self) -> None:
        from seerflow.pipeline import run as run_mod

        src = function_source_text(run_mod._run_with_config)

        idx_should_exit = src.find("server.should_exit = True")
        # ``storage.close`` appears twice: once in the early build_pipeline
        # error path (start-up failure) and once in the cleanup finally
        # block. The shutdown ordering invariant only applies to the
        # cleanup-path occurrence — use the last index.
        idx_storage_close = src.rfind("await storage.close()")
        assert idx_should_exit != -1, "uvicorn shutdown signal missing"
        assert idx_storage_close != -1, "storage.close() missing"
        assert idx_should_exit < idx_storage_close, "uvicorn must stop before storage.close()"

    def test_uses_asyncio_wait_first_completed(self) -> None:
        from seerflow.pipeline import run as run_mod

        src = function_source_text(run_mod._run_with_config)
        assert "FIRST_COMPLETED" in src
        assert "pipeline_task" in src


class TestSigtermWiresUvicorn:
    def test_helper_replaces_inline_signal_block(self) -> None:
        from seerflow.pipeline import run as run_mod

        src = function_source_text(run_mod._run_with_config)
        assert "_install_shutdown_handlers(" in src
        # The legacy `nonlocal _shutdown_task` pattern must be gone.
        assert "_shutdown_task" not in src

    def test_uvicorn_install_signal_handlers_is_suppressed_in_correct_order(self) -> None:
        from seerflow.pipeline import run as run_mod

        src = function_source_text(run_mod._run_with_config)
        idx_server = src.find("server = uvicorn.Server(")
        # Modern uvicorn (>=0.20) uses ``capture_signals`` instead of the
        # legacy ``install_signal_handlers`` the plan referenced; either form
        # is acceptable as long as it appears in the suppression slot.
        idx_suppress = max(
            src.find("server.capture_signals = "),
            src.find("server.install_signal_handlers = lambda"),
        )
        idx_assign = src.find("shutdown_ctx.server = server")
        idx_task = src.find("server_task = asyncio.create_task")
        assert -1 < idx_server < idx_suppress < idx_task, (
            "uvicorn signal-handler suppression must appear AFTER server construction "
            "and BEFORE server_task creation"
        )
        assert -1 < idx_server < idx_assign < idx_task, (
            "shutdown_ctx.server assignment must appear AFTER server construction "
            "and BEFORE server_task creation"
        )

    def test_helper_sets_should_exit_in_source(self) -> None:
        from seerflow.pipeline import run as run_mod

        helper_src = function_source_text(run_mod._install_shutdown_handlers)
        assert "ctx.server.should_exit = True" in helper_src
        assert "asyncio.create_task(pipeline.stop())" in helper_src
