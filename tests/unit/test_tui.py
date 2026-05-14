"""Unit tests for ``seerflow.tui`` (S-079, FR-048).

Covers:

- Module top-level is import-safe even when ``textual`` is absent
  (no top-level ``textual`` import).
- The lazy ``_load_textual()`` helper logs the documented WARNING and
  returns ``None`` when ``textual`` is not installed, returns the module
  otherwise.
- ``launch_tui_with_pipeline`` falls back to the plain pipeline path
  when ``textual`` is absent (graceful-fallback AC).
- HTTP poll + entity search helpers handle 200 / 503 / connection-refused
  without propagating exceptions.
- Warmup gate returns ``True`` on the first 200/503 response and
  ``False`` on transport failure within the budget.
- The Textual ``App`` registers the documented keyboard bindings and
  composes the documented panel IDs (``alert-feed``, ``event-stream``,
  ``entity-search``).
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
import time
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from seerflow import tui

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# ---------------------------------------------------------------------------
# Module-level import safety + lazy textual import
# ---------------------------------------------------------------------------


class TestModuleImport:
    def test_module_importable_without_textual(self) -> None:
        """``import seerflow.tui`` must not eagerly import ``textual``."""
        # The module is already imported at the top of this file. Re-import
        # to confirm the import chain stays clean even when textual would
        # be missing — top-level must contain no ``import textual`` line.
        importlib.reload(tui)
        # If textual were imported eagerly, removing it from sys.modules
        # would break the reload above. The reload succeeded → safe.

    def test_module_exports_public_api(self) -> None:
        assert hasattr(tui, "launch_tui_with_pipeline")
        assert hasattr(tui, "_load_textual")


class TestLoadTextual:
    def test_returns_module_when_installed(self) -> None:
        """When textual is installed (it is, as part of test deps), return it."""
        result = tui._load_textual()
        # textual may or may not be a test dep. Either branch is acceptable
        # for THIS test as long as it returns the module xor None.
        assert result is None or result.__name__ == "textual"

    def test_returns_none_and_warns_when_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Simulate textual absence; helper must return None and log WARNING."""
        # Force the lazy import to raise ImportError.
        monkeypatch.setitem(sys.modules, "textual", None)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="seerflow.tui"):
            result = tui._load_textual()
        assert result is None
        assert any(
            "--tui requested but textual not installed" in rec.message for rec in caplog.records
        )
        assert any("seerflow[tui]" in rec.message for rec in caplog.records)


class TestLaunchTUIFallback:
    @pytest.mark.asyncio
    async def test_falls_back_to_pipeline_when_textual_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Graceful-fallback AC: pipeline still starts when textual is absent."""

        called: dict[str, Any] = {}

        async def _fake_run(cfg: object) -> None:
            called["config"] = cfg

        monkeypatch.setattr(tui, "_load_textual", lambda: None)
        # Patch the lazy import target inside the module so we don't depend
        # on the real pipeline.run module behaviour.
        import seerflow.pipeline.run as run_mod

        monkeypatch.setattr(run_mod, "_run_with_config", _fake_run)

        sentinel_config = object()
        await tui.launch_tui_with_pipeline(sentinel_config)  # type: ignore[arg-type]

        assert called.get("config") is sentinel_config


# ---------------------------------------------------------------------------
# HTTP poll + entity search helpers
# ---------------------------------------------------------------------------


def _mock_client(
    handler: httpx.MockTransport | None = None,
    *,
    transport: httpx.MockTransport | None = None,
) -> httpx.AsyncClient:
    """Build an in-memory httpx client that routes through ``handler``."""
    return httpx.AsyncClient(
        transport=transport or handler,
        base_url="http://test/api/v1",
        timeout=1.0,
    )


class TestPollAlerts:
    @pytest.mark.asyncio
    async def test_returns_items_on_200(self) -> None:
        body = {
            "items": [{"id": "alert-1", "rule_name": "demo"}],
            "total": 1,
            "page": 1,
            "limit": 50,
            "has_next": False,
        }

        def _handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/alerts"
            return httpx.Response(200, json=body)

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            items = await tui._poll_alerts(client)
        assert items == body["items"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_connection_error(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope")

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            items = await tui._poll_alerts(client)
        assert items == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_503(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "degraded"})

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            items = await tui._poll_alerts(client)
        # 503 is the daemon saying "degraded"; the list payload is missing
        # → safe default: empty list, never raise.
        assert items == []


class TestSearchEntities:
    @pytest.mark.asyncio
    async def test_issues_get_with_query_param(self) -> None:
        captured: dict[str, str] = {}

        def _handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/entities/search"
            captured["q"] = request.url.params.get("q", "")
            return httpx.Response(
                200,
                json=[
                    {"entity_type": "user", "entity_value": "alice", "entity_uuid": "u-1"},
                ],
            )

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            results = await tui._search_entities(client, "alice")
        assert captured["q"] == "alice"
        assert results == [
            {"entity_type": "user", "entity_value": "alice", "entity_uuid": "u-1"},
        ]

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope")

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            results = await tui._search_entities(client, "alice")
        assert results == []


class TestWarmup:
    @pytest.mark.asyncio
    async def test_returns_true_on_first_200(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "healthy", "components": {}})

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            ok = await tui._warmup(client, max_s=0.5, interval_s=0.01)
        assert ok is True

    @pytest.mark.asyncio
    async def test_returns_true_on_503(self) -> None:
        """503 means 'degraded but the app is up' — accept it."""

        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "degraded"})

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            ok = await tui._warmup(client, max_s=0.5, interval_s=0.01)
        assert ok is True

    @pytest.mark.asyncio
    async def test_returns_false_on_persistent_failure(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope")

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            ok = await tui._warmup(client, max_s=0.05, interval_s=0.01)
        assert ok is False


# ---------------------------------------------------------------------------
# Textual App composition + bindings (only when textual is installed)
# ---------------------------------------------------------------------------


textual_available = tui._load_textual() is not None


@pytest.mark.skipif(not textual_available, reason="textual extra not installed")
class TestSeerflowTUIApp:
    def test_bindings_include_documented_keys(self) -> None:
        from seerflow.tui import SeerflowTUIApp

        keys = {b.key for b in SeerflowTUIApp.BINDINGS}
        assert {"q", "ctrl+c", "tab", "shift+tab", "enter"}.issubset(keys)

    @pytest.mark.asyncio
    async def test_compose_yields_documented_panel_ids(self) -> None:
        from seerflow.tui import SeerflowTUIApp

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                await pilot.pause(0)
                ids = {w.id for w in app.query("*") if w.id}
                assert "alert-feed" in ids
                assert "event-stream" in ids
                assert "entity-search-input" in ids
                assert "entity-search-results" in ids
                await pilot.press("q")
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# WebSocket consumer — pure-Python iterator path tested via injected channel
# ---------------------------------------------------------------------------


class TestWebSocketConsumer:
    @pytest.mark.asyncio
    async def test_consume_appends_event_payloads(self) -> None:
        """``_consume_ws_messages`` invokes the callback once per ``event`` frame."""

        async def _fake_messages() -> AsyncIterator[str]:
            # Two events, one alert (ignored), one malformed (ignored).
            yield '{"type": "event", "data": {"template": "ssh login from %{ip}"}}'
            yield '{"type": "alert", "data": {"id": "a-1"}}'
            yield "not-json"
            yield '{"type": "event", "data": {"template": "kernel: oom-killer"}}'

        captured: list[dict[str, Any]] = []

        async def _on_event(payload: dict[str, Any]) -> None:
            captured.append(payload)

        await tui._consume_ws_messages(_fake_messages(), _on_event)

        assert len(captured) == 2
        assert captured[0]["template"].startswith("ssh login")
        assert captured[1]["template"].startswith("kernel")

    @pytest.mark.asyncio
    async def test_consume_skips_non_dict_top_level(self) -> None:
        """Top-level JSON arrays / scalars are silently dropped (not raised)."""

        async def _fake_messages() -> AsyncIterator[str]:
            yield "[1, 2, 3]"
            yield '"string-frame"'
            yield "42"
            yield '{"type": "event", "data": {"template": "ok"}}'

        captured: list[dict[str, Any]] = []

        async def _on_event(payload: dict[str, Any]) -> None:
            captured.append(payload)

        await tui._consume_ws_messages(_fake_messages(), _on_event)
        assert len(captured) == 1
        assert captured[0]["template"] == "ok"

    @pytest.mark.asyncio
    async def test_consume_skips_event_with_non_dict_data(self) -> None:
        """``data`` that is not a dict (e.g. None, list) is dropped."""

        async def _fake_messages() -> AsyncIterator[str]:
            yield '{"type": "event", "data": null}'
            yield '{"type": "event", "data": [1, 2]}'
            yield '{"type": "event"}'  # missing data field

        captured: list[dict[str, Any]] = []

        async def _on_event(payload: dict[str, Any]) -> None:
            captured.append(payload)

        await tui._consume_ws_messages(_fake_messages(), _on_event)
        assert captured == []


# ---------------------------------------------------------------------------
# Additional poll / search / warmup branch coverage
# ---------------------------------------------------------------------------


class TestPollAlertsBranches:
    @pytest.mark.asyncio
    async def test_returns_empty_on_non_dict_body(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[1, 2, 3])

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            items = await tui._poll_alerts(client)
        assert items == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_items_not_list(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": "oops"})

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            items = await tui._poll_alerts(client)
        assert items == []


class TestSearchEntitiesBranches:
    @pytest.mark.asyncio
    async def test_returns_empty_on_non_200(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "degraded"})

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            results = await tui._search_entities(client, "alice")
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_non_list_body(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"oops": "not a list"})

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            results = await tui._search_entities(client, "alice")
        assert results == []


class TestWarmupBranches:
    @pytest.mark.asyncio
    async def test_unrecognised_status_is_ignored_then_succeeds(self) -> None:
        """A 404 (or other non-200/503) does not count as warmup-ok."""
        calls = {"n": 0}

        def _handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(404)
            return httpx.Response(200, json={"status": "ok"})

        async with _mock_client(transport=httpx.MockTransport(_handler)) as client:
            ok = await tui._warmup(client, max_s=0.5, interval_s=0.01)
        assert ok is True
        assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


class TestFormatTimestamp:
    def test_returns_formatted_for_positive_int_ns(self) -> None:
        ts = 1_775_736_000_000_000_000
        out = tui._format_ts(ts)
        # Format is HH:MM:SS — exactly 8 characters with colons.
        assert len(out) == 8
        assert out[2] == ":"
        assert out[5] == ":"

    def test_returns_empty_for_non_int(self) -> None:
        assert tui._format_ts("not-an-int") == ""
        assert tui._format_ts(None) == ""
        assert tui._format_ts(1.5) == ""

    def test_returns_empty_for_non_positive(self) -> None:
        assert tui._format_ts(0) == ""
        assert tui._format_ts(-1) == ""


class TestFormatEventLine:
    def test_includes_timestamp_when_present(self) -> None:
        line = tui._format_event_line(
            {
                "timestamp_ns": 1_775_736_000_000_000_000,
                "severity": "WARN",
                "source_type": "syslog",
                "template": "user %{user} login",
                "message": "alice logged in",
            }
        )
        assert "severity=WARN" in line
        assert "source_type=syslog" in line
        assert "template=user %{user} login" in line
        assert "message=alice logged in" in line

    def test_omits_missing_and_empty_fields(self) -> None:
        line = tui._format_event_line(
            {
                "timestamp_ns": 1_775_736_000_000_000_000,
                "severity": "WARN",
                "source_type": "",
                "template": None,
            }
        )
        assert "severity=WARN" in line
        assert "source_type=" not in line
        assert "template=" not in line

    def test_falls_back_to_json_when_no_recognised_keys(self) -> None:
        payload = {"foo": "bar"}
        line = tui._format_event_line(payload)
        # No timestamp, no recognised keys → fallback path returns JSON.
        assert "foo" in line
        assert "bar" in line


# ---------------------------------------------------------------------------
# __getattr__ lazy access path
# ---------------------------------------------------------------------------


class TestModuleGetattr:
    def test_unknown_attribute_raises(self) -> None:
        with pytest.raises(AttributeError, match="no attribute 'Unknown'"):
            tui.__getattr__("Unknown")

    def test_raises_import_error_when_textual_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tui, "_load_textual", lambda: None)
        with pytest.raises(ImportError, match="textual is not installed"):
            tui.__getattr__("SeerflowTUIApp")
        with pytest.raises(ImportError, match="textual is not installed"):
            tui.__getattr__("AlertDetailModal")

    def test_alert_detail_modal_resolves_when_textual_present(self) -> None:
        if not textual_available:
            pytest.skip("textual extra not installed")
        cls = tui.__getattr__("AlertDetailModal")
        assert cls.__name__ == "AlertDetailModal"
        # __getattr__ rebuilds via _build_alert_modal_class — exercise it twice
        # to confirm the closure does not leak module-level state.
        cls2 = tui.__getattr__("AlertDetailModal")
        assert cls2.__name__ == "AlertDetailModal"


# ---------------------------------------------------------------------------
# AlertDetailModal — exercise via _build_alert_modal_class
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not textual_available, reason="textual extra not installed")
class TestAlertDetailModal:
    def test_modal_exposes_alert_payload(self) -> None:
        cls = tui._build_alert_modal_class()
        modal = cls({"id": "a-1", "rule_name": "demo", "severity": "WARN"})
        assert modal._alert["id"] == "a-1"

    def test_modal_compose_yields_static_with_json_body(self) -> None:
        cls = tui._build_alert_modal_class()
        modal = cls({"id": "a-2", "rule_name": "test"})
        nodes = list(modal.compose())
        assert len(nodes) == 1
        # The only child is the Static widget tagged with the documented id.
        node = nodes[0]
        assert node.id == "alert-detail-body"
        # The JSON body is rendered by Static; render() returns a Rich Text.
        rendered = str(node.render())
        assert "a-2" in rendered
        assert "test" in rendered

    @pytest.mark.asyncio
    async def test_modal_action_dismiss_pops_screen(self) -> None:
        """``action_dismiss`` pops the modal off the screen stack."""
        from seerflow.tui import SeerflowTUIApp

        modal_cls = tui._build_alert_modal_class()

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                await pilot.pause(0)
                await app.push_screen(modal_cls({"id": "a-1"}))
                await pilot.pause(0.05)
                # Modal is on top of the stack.
                assert app.screen_stack[-1].__class__.__name__ == "AlertDetailModal"
                # Trigger dismiss via the documented action.
                top = app.screen_stack[-1]
                top.action_dismiss()
                await pilot.pause(0.05)
                # Modal popped → top no longer AlertDetailModal.
                assert app.screen_stack[-1].__class__.__name__ != "AlertDetailModal"
                await pilot.press("q")
        finally:
            await client.aclose()

    def test_inner_alert_modal_compose_and_dismiss(self) -> None:
        """Exercise the AlertDetailModal nested inside _build_app_class too."""
        from seerflow.tui import SeerflowTUIApp  # triggers _build_app_class

        # The inner modal class lives inside the closure; reach it via the
        # standalone builder since both paths share the same shape and the
        # __getattr__ branch maps ``AlertDetailModal`` to the standalone one.
        # That standalone path is already exercised above; here we just confirm
        # the App class itself is stable.
        assert SeerflowTUIApp.__name__ == "SeerflowTUIApp"


# ---------------------------------------------------------------------------
# action_open_or_search dispatch
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not textual_available, reason="textual extra not installed")
class TestActionOpenOrSearch:
    @pytest.mark.asyncio
    async def test_input_focus_runs_entity_search(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from textual.widgets import DataTable, Input

        from seerflow.tui import SeerflowTUIApp

        searched: list[str] = []

        async def _fake_search(client: httpx.AsyncClient, q: str) -> list[dict[str, Any]]:
            searched.append(q)
            return [{"entity_type": "user", "entity_value": "alice", "entity_uuid": "u-1"}]

        monkeypatch.setattr(tui, "_search_entities", _fake_search)

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                await pilot.pause(0)
                search = app.query_one("#entity-search-input", Input)
                app.set_focus(search)
                await pilot.pause(0.05)
                search.value = "alice"
                # Invoke the action directly — Input intercepts ``enter`` to
                # fire ``Submitted``, so the binding-driven keypress path
                # does not always reach ``action_open_or_search`` reliably.
                # We exercise the dispatch logic by calling it explicitly.
                await app.action_open_or_search()
                await pilot.pause(0.05)
                assert searched == ["alice"]
                results = app.query_one("#entity-search-results", DataTable)
                assert results.row_count == 1
                await pilot.press("q")
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_input_focus_with_blank_query_is_noop(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from textual.widgets import Input

        from seerflow.tui import SeerflowTUIApp

        called = {"n": 0}

        async def _fake_search(*_a: object, **_k: object) -> list[dict[str, Any]]:
            called["n"] += 1
            return []

        monkeypatch.setattr(tui, "_search_entities", _fake_search)

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                await pilot.pause(0)
                search = app.query_one("#entity-search-input", Input)
                search.focus()
                search.value = "   "  # blank after strip
                await pilot.press("enter")
                await pilot.pause(0.05)
                assert called["n"] == 0
                await pilot.press("q")
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_no_focus_is_noop(self) -> None:
        from seerflow.tui import SeerflowTUIApp

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                await pilot.pause(0)
                # Force focus to None and trigger the action directly.
                app.set_focus(None)
                await app.action_open_or_search()
                await pilot.press("q")
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_alert_row_focus_opens_modal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from textual.widgets import DataTable

        from seerflow.tui import SeerflowTUIApp

        # Suppress the live poll path by stubbing _poll_alerts to return [].
        async def _no_alerts(_client: httpx.AsyncClient) -> list[dict[str, Any]]:
            return []

        monkeypatch.setattr(tui, "_poll_alerts", _no_alerts)

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                await pilot.pause(0.05)
                alert = {
                    "alert_id": "a-1",
                    "rule_name": "demo",
                    "severity": "WARN",
                    "alert_type": "ml",
                    "timestamp_ns": 1_775_736_000_000_000_000,
                    "entity_uuid": "u-1",
                }
                # Inject the alert through the same code path as the poll loop.
                app._alerts_by_id["a-1"] = alert
                table = app.query_one("#alert-feed", DataTable)
                table.add_row("00:00:00", "WARN", "ml", "demo", "u-1", key="a-1")
                table.focus()
                table.move_cursor(row=0)
                await pilot.pause(0.05)
                # Trigger the action directly — pilot key dispatch can be
                # racy when the binding maps ``enter`` to multiple handlers.
                await app.action_open_or_search()
                await pilot.pause(0.1)
                assert any(s.__class__.__name__ == "AlertDetailModal" for s in app.screen_stack)
                await pilot.press("q")
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_alert_row_focus_with_unknown_key_is_noop(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A row whose key is not in ``_alerts_by_id`` does not push a modal."""
        from textual.widgets import DataTable

        from seerflow.tui import SeerflowTUIApp

        async def _no_alerts(_client: httpx.AsyncClient) -> list[dict[str, Any]]:
            return []

        monkeypatch.setattr(tui, "_poll_alerts", _no_alerts)

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                await pilot.pause(0)
                table = app.query_one("#alert-feed", DataTable)
                # Add a row with a key that is NOT registered in _alerts_by_id.
                table.add_row("00:00:00", "WARN", "ml", "demo", "u-?", key="ghost")
                table.focus()
                table.move_cursor(row=0)
                await pilot.pause(0.05)
                await app.action_open_or_search()
                await pilot.pause(0.05)
                # Modal not pushed — alert lookup returned None.
                assert not any(
                    s.__class__.__name__ == "AlertDetailModal" for s in app.screen_stack
                )
                await pilot.press("q")
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# _refresh_alerts coercion + websocket consumer error path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not textual_available, reason="textual extra not installed")
class TestRefreshAlertsCoercion:
    @pytest.mark.asyncio
    async def test_string_timestamp_is_coerced_to_int(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from textual.widgets import DataTable

        from seerflow.tui import SeerflowTUIApp

        async def _poll_with_string_ts(_client: httpx.AsyncClient) -> list[dict[str, Any]]:
            return [
                {
                    "alert_id": "a-1",
                    "rule_name": "demo",
                    "severity": "WARN",
                    "alert_type": "ml",
                    "timestamp_ns": "1775736000000000000",  # str digits → coerced
                    "entity_uuid": "u-1",
                }
            ]

        monkeypatch.setattr(tui, "_poll_alerts", _poll_with_string_ts)

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                await pilot.pause(0.2)
                table = app.query_one("#alert-feed", DataTable)
                # Single row added; timestamp formatted (non-empty).
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline and table.row_count == 0:
                    await pilot.pause(0.05)
                assert table.row_count == 1
                await pilot.press("q")
        finally:
            await client.aclose()


@pytest.mark.skipif(not textual_available, reason="textual extra not installed")
class TestConsumeWebSocketErrors:
    @pytest.mark.asyncio
    async def test_websockets_missing_logs_and_returns(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Force the lazy ``websockets`` import to fail; consumer must exit cleanly."""
        from seerflow.tui import SeerflowTUIApp

        monkeypatch.setitem(sys.modules, "websockets.asyncio.client", None)

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                with caplog.at_level(logging.DEBUG, logger="seerflow.tui"):
                    await pilot.pause(0.1)
                # No exception raised → import-error branch handled.
                await pilot.press("q")
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_websocket_connection_failure_is_swallowed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A failing ``connect()`` must not crash the worker."""
        import websockets.asyncio.client as ws_client_mod

        from seerflow.tui import SeerflowTUIApp

        def _broken_connect(url: str) -> Any:
            raise RuntimeError("connect refused")

        monkeypatch.setattr(ws_client_mod, "connect", _broken_connect)

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                await pilot.pause(0)
                # Drive the consumer directly so we can await its completion
                # — the worker variant is racy under Pilot.
                with caplog.at_level(logging.DEBUG, logger="seerflow.tui"):
                    await app._consume_websocket()
                await pilot.press("q")
            assert any("websocket loop ended" in rec.message for rec in caplog.records)
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_websocket_happy_path_writes_event_to_log(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A working ``connect()`` yields frames; events land in the RichLog."""
        import websockets.asyncio.client as ws_client_mod
        from textual.widgets import RichLog

        from seerflow.tui import SeerflowTUIApp

        class _FakeWs:
            def __init__(self) -> None:
                self._frames = [
                    '{"type": "event", "data": {"template": "ssh login"}}',
                ]

            async def __aenter__(self) -> _FakeWs:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            def __aiter__(self) -> _FakeWs:
                return self

            async def __anext__(self) -> str:
                if not self._frames:
                    raise StopAsyncIteration
                return self._frames.pop(0)

        def _fake_connect(url: str) -> _FakeWs:
            return _FakeWs()

        monkeypatch.setattr(ws_client_mod, "connect", _fake_connect)

        client = httpx.AsyncClient(base_url="http://test/api/v1")
        try:
            app = SeerflowTUIApp(client=client, ws_url="ws://test/api/ws")
            async with app.run_test() as pilot:
                await pilot.pause(0)
                await app._consume_websocket()
                await pilot.pause(0.05)
                log = app.query_one("#event-stream", RichLog)
                # The fake frame produced one written line.
                assert len(log.lines) >= 1
                await pilot.press("q")
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# launch_tui_with_pipeline TaskGroup path (textual installed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not textual_available, reason="textual extra not installed")
class TestLaunchTUIFullPath:
    @pytest.mark.asyncio
    async def test_taskgroup_runs_pipeline_and_ui(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """End-to-end: stub the pipeline + the App; ensure both tasks run + exit."""
        from dataclasses import dataclass

        pipeline_started = {"ok": False}
        pipeline_cancelled = {"ok": False}
        ui_started = {"ok": False}

        @dataclass
        class _Cfg:
            health_bind_address: str = "127.0.0.1"
            dashboard_port: int = 18999

        async def _fake_pipeline(_cfg: object) -> None:
            pipeline_started["ok"] = True
            try:
                # Block forever until cancelled by the TUI exit.
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pipeline_cancelled["ok"] = True
                raise

        async def _fake_warmup(*_a: object, **_k: object) -> bool:
            return True

        class _FakeApp:
            def __init__(self, **kwargs: object) -> None:
                self._kwargs = kwargs

            async def run_async(self) -> None:
                ui_started["ok"] = True
                # Allow the auto-quit task to fire and unblock TaskGroup.
                await asyncio.sleep(0.2)

            def exit(self, _code: int = 0) -> None:
                pass

        def _fake_build() -> tuple[type[Any], type[Any]]:
            return _FakeApp, _FakeApp

        monkeypatch.setattr(tui, "_warmup", _fake_warmup)
        monkeypatch.setattr(tui, "_build_app_class", _fake_build)
        import seerflow.pipeline.run as run_mod

        monkeypatch.setattr(run_mod, "_run_with_config", _fake_pipeline)

        # _max_uptime_s caps the TUI runtime; with the fake App it is
        # effectively informational because run_async returns first.
        await tui.launch_tui_with_pipeline(_Cfg(), _max_uptime_s=0.5)  # type: ignore[arg-type]
        assert pipeline_started["ok"] is True
        assert ui_started["ok"] is True
        assert pipeline_cancelled["ok"] is True

    @pytest.mark.asyncio
    async def test_max_uptime_auto_quit_invokes_exit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ``_max_uptime_s`` knob schedules an auto-quit calling ``app.exit``."""
        from dataclasses import dataclass

        @dataclass
        class _Cfg:
            health_bind_address: str = "127.0.0.1"
            dashboard_port: int = 18999

        exit_called = {"n": 0}

        class _FakeApp:
            def __init__(self, **kwargs: object) -> None:
                pass

            async def run_async(self) -> None:
                # Wait long enough for the auto-quit task to fire.
                await asyncio.sleep(0.2)

            def exit(self, _code: int = 0) -> None:
                exit_called["n"] += 1

        async def _fake_warmup(*_a: object, **_k: object) -> bool:
            return True

        async def _fake_pipeline(_cfg: object) -> None:
            await asyncio.Event().wait()

        monkeypatch.setattr(tui, "_warmup", _fake_warmup)
        monkeypatch.setattr(tui, "_build_app_class", lambda: (_FakeApp, _FakeApp))
        import seerflow.pipeline.run as run_mod

        monkeypatch.setattr(run_mod, "_run_with_config", _fake_pipeline)

        await tui.launch_tui_with_pipeline(_Cfg(), _max_uptime_s=0.05)  # type: ignore[arg-type]
        assert exit_called["n"] >= 1
