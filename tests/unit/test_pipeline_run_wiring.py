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
    """One ``ConnectionManager`` shared by the pipeline handler and the
    FastAPI app.

    S-304 changed *how* the shared manager is wired (not the invariant):
    before S-304 ``create_api_app`` built it internally and
    ``_run_with_config`` read it back off ``api_app.state.ws_manager``;
    after S-304 the engine assembly moved into
    ``pipeline.assembly.assemble_handler`` (the S-302 extraction), so the
    ``ConnectionManager`` + ``AnomalyTimelineRing`` are built ONCE in
    ``_run_with_config`` via ``build_ws_manager`` and injected into BOTH
    ``assemble_handler`` (so the pipeline handler broadcasts) and
    ``create_api_app`` (so the ``/api/v1/ws`` route shares the same
    fan-out). The behaviour — one manager, both sides — is preserved; this
    test pins the new construction strategy so a regression that splits the
    manager fails here.
    """

    def test_single_ws_manager_built_and_injected_both_ways(self) -> None:
        import re

        from seerflow.pipeline import run as run_mod

        src = function_source_text(run_mod._run_with_config)
        # Built ONCE via the public factory wrapper, carrying the shared ring.
        assert re.search(r"ws_manager\s*:\s*ConnectionManager\s*=\s*build_ws_manager\(", src), (
            "expected the ConnectionManager to be built once via build_ws_manager(...)"
        )
        # Injected into the detection factory so the pipeline handler
        # broadcasts (S-304 additive ws_manager kwarg on assemble_handler).
        assert re.search(
            r"assemble_handler\(\s*config,\s*storage,\s*ws_manager=ws_manager\s*\)", src
        ), "expected assemble_handler(config, storage, ws_manager=ws_manager)"
        # Injected into the FastAPI app so the WS route shares the fan-out.
        assert re.search(r"ws_manager\s*=\s*ws_manager\b", src), (
            "expected `ws_manager=ws_manager` passed to make_api_app"
        )
        # The shared AnomalyTimelineRing is reused on app.state so the
        # /api/v1/anomaly route reads the ring the manager records into.
        assert "api_app.state.anomaly_timeline_ring = timeline_ring" in src, (
            "expected the injected manager's timeline ring to be reused on "
            "api_app.state so the anomaly route and the WS manager share it"
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
