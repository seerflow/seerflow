"""``seerflow start --tui`` — Textual TUI headless dashboard (S-079, FR-048).

The TUI is a localhost client of the running FastAPI app. It launches alongside
the pipeline (same process, same asyncio loop, structured concurrency via
``asyncio.TaskGroup``) and consumes the loopback HTTP + WebSocket endpoints —
the same surface the React dashboard and the ``seerflow status`` CLI consume.

Three panels:

- **Alert Feed** — ``DataTable`` polling ``GET /api/v1/alerts`` every 2 s.
- **Event Stream** — ``RichLog`` streaming live frames from ``/api/ws``.
- **Entity Search** — ``Input`` + ``DataTable`` calling ``GET /api/v1/entities/search``.

Keyboard bindings: ``tab`` / ``shift+tab`` cycle focus, ``enter`` either opens
an alert detail modal or submits an entity search depending on focus, ``q``
or ``ctrl+c`` quit cleanly.

Graceful absence: ``textual`` is an optional extra (``pip install seerflow[tui]``).
When the import fails the helper logs one WARNING line and falls back to the
plain pipeline path — the daemon still starts, only the TUI is dropped. This
mirrors the ``llm-cpu`` / ``llm-cloud`` graceful-absence pattern.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any, ClassVar

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Awaitable, Callable
    from types import ModuleType

    from seerflow.config import SeerflowConfig

_log = logging.getLogger("seerflow.tui")

_MISSING_HINT = (
    "--tui requested but textual not installed; install with "
    "'pip install seerflow[tui]'. Continuing without TUI."
)

# Bounded so the RichLog consumer never balloons memory on a busy stream.
_EVENT_LOG_MAX_LINES = 1_000
_ALERT_POLL_INTERVAL_S = 2.0
_ALERT_PAGE_LIMIT = 50
_DEFAULT_HTTP_TIMEOUT_S = 2.0
_WARMUP_BUDGET_S = 5.0
_WARMUP_INTERVAL_S = 0.1


# ---------------------------------------------------------------------------
# Lazy textual import
# ---------------------------------------------------------------------------


def _load_textual() -> ModuleType | None:
    """Import ``textual`` lazily; return ``None`` and log a hint when absent.

    The import is intentionally inside the function (not at module top
    level) so ``import seerflow.tui`` stays safe on systems that did not
    install the optional extra. Pattern mirrors
    ``seerflow.llm.backends.cloud._import_anthropic``.
    """
    try:
        import textual as _textual_module
    except ImportError:
        _log.warning(_MISSING_HINT)
        return None
    return _textual_module


# ---------------------------------------------------------------------------
# HTTP helpers — exposed at module level so unit tests can drive them with
# httpx.MockTransport without spinning up the Textual App.
# ---------------------------------------------------------------------------


async def _warmup(
    client: httpx.AsyncClient,
    *,
    max_s: float = _WARMUP_BUDGET_S,
    interval_s: float = _WARMUP_INTERVAL_S,
) -> bool:
    """Poll ``/health`` until the daemon answers (200 or 503) or budget expires.

    Returns ``True`` on the first HTTP response (the daemon is up — 503 is a
    legitimate "degraded" reply that still means "the app is bound"), and
    ``False`` when the budget elapses without a single successful TCP
    handshake. The TUI tolerates either outcome — a ``False`` warmup just
    means the first poll cycle inside the App will retry.
    """
    deadline = time.monotonic() + max_s
    while time.monotonic() < deadline:
        try:
            resp = await client.get("/health")
        except httpx.HTTPError:
            await asyncio.sleep(interval_s)
            continue
        if resp.status_code in (200, 503):
            return True
        await asyncio.sleep(interval_s)
    return False


async def _poll_alerts(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Fetch the most recent alerts from ``/alerts`` (errors swallowed)."""
    try:
        resp = await client.get(
            "/alerts",
            params={"limit": _ALERT_PAGE_LIMIT, "page": 1},
        )
    except httpx.HTTPError as exc:
        _log.debug("tui: alert poll failed: %s", type(exc).__name__)
        return []
    if resp.status_code != 200:
        return []
    body = resp.json()
    items = body.get("items") if isinstance(body, dict) else None
    return list(items) if isinstance(items, list) else []


async def _search_entities(
    client: httpx.AsyncClient,
    query: str,
) -> list[dict[str, Any]]:
    """Call ``GET /entities/search?q=<query>`` (errors swallowed)."""
    try:
        resp = await client.get("/entities/search", params={"q": query})
    except httpx.HTTPError as exc:
        _log.debug("tui: entity search failed: %s", type(exc).__name__)
        return []
    if resp.status_code != 200:
        return []
    body = resp.json()
    return list(body) if isinstance(body, list) else []


async def _consume_ws_messages(
    messages: AsyncIterable[str],
    on_event: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Forward ``event``-typed WebSocket frames to ``on_event``.

    Frames that fail to parse, or carry a non-``event`` ``type`` field, are
    silently dropped — the alert feed has its own poll path and the TUI
    must not crash on a single malformed broadcast.
    """
    async for raw in messages:
        try:
            frame = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(frame, dict):
            continue
        if frame.get("type") != "event":
            continue
        data = frame.get("data")
        if isinstance(data, dict):
            await on_event(data)


# ---------------------------------------------------------------------------
# Textual App — only constructed when the optional extra is installed.
# ---------------------------------------------------------------------------


def _build_app_class() -> type[Any]:
    """Construct the Textual ``App`` subclass.

    Defined inside a function so the textual imports stay lazy. Callers
    (``launch_tui_with_pipeline``) only invoke this after ``_load_textual``
    confirms the extra is present.
    """
    # Imports here are protected by the `_load_textual()` gate at the call
    # site — they never run on the import-safe path.
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.screen import ModalScreen
    from textual.widgets import (
        DataTable,
        Footer,
        Header,
        Input,
        RichLog,
        Static,
    )

    # The Textual base classes type ``BINDINGS`` as an invariant
    # ``list[Binding | tuple[...]]``. We pin our overrides to the precise
    # ``list[Binding]`` shape so the runtime check + the test assertions
    # both stay tight; the mypy assignment-override warning is the price
    # of the invariance, suppressed locally.
    class AlertDetailModal(ModalScreen[None]):
        """Read-only modal showing the full JSON body of one alert."""

        BINDINGS: ClassVar[list[Binding]] = [  # type: ignore[assignment]
            Binding("escape", "dismiss", "Close", show=True),
        ]

        def __init__(self, alert: dict[str, Any]) -> None:
            super().__init__()
            self._alert = alert

        def compose(self) -> ComposeResult:
            yield Static(
                json.dumps(self._alert, indent=2, sort_keys=True, default=str),
                id="alert-detail-body",
            )

        def action_dismiss(self) -> None:  # type: ignore[override]
            self.app.pop_screen()

    class SeerflowTUIApp(App[int]):
        """Textual app composing alert feed, event stream, entity search."""

        CSS = """
        Vertical#root { height: 1fr; }
        DataTable#alert-feed { height: 40%; }
        RichLog#event-stream { height: 40%; border: solid $accent; }
        Vertical#search-pane { height: 20%; border: solid $accent; }
        Input#entity-search-input { height: 3; }
        DataTable#entity-search-results { height: 1fr; }
        """

        BINDINGS: ClassVar[list[Binding]] = [  # type: ignore[assignment]
            Binding("q", "quit", "Quit", show=True),
            Binding("ctrl+c", "quit", "Quit", show=False),
            Binding("tab", "focus_next", "Next panel", show=True),
            Binding("shift+tab", "focus_previous", "Prev panel", show=False),
            Binding("enter", "open_or_search", "Open / Search", show=True),
        ]

        def __init__(
            self,
            *,
            client: httpx.AsyncClient,
            ws_url: str,
            poll_interval_s: float = _ALERT_POLL_INTERVAL_S,
        ) -> None:
            super().__init__()
            self._client = client
            self._ws_url = ws_url
            self._poll_interval_s = poll_interval_s
            self._alerts_by_id: dict[str, dict[str, Any]] = {}

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            with Vertical(id="root"):
                yield DataTable(id="alert-feed", cursor_type="row")
                yield RichLog(
                    id="event-stream",
                    max_lines=_EVENT_LOG_MAX_LINES,
                    highlight=True,
                    markup=False,
                )
                with Vertical(id="search-pane"):
                    yield Input(
                        placeholder="Entity search (e.g. alice or 10.0.0.1)…",
                        id="entity-search-input",
                    )
                    yield DataTable(
                        id="entity-search-results",
                        cursor_type="row",
                    )
            yield Footer()

        def on_mount(self) -> None:
            alerts = self.query_one("#alert-feed", DataTable)
            alerts.add_columns("Time", "Severity", "Type", "Rule", "Entity")

            results = self.query_one("#entity-search-results", DataTable)
            results.add_columns("Type", "Value", "UUID")

            self.set_interval(self._poll_interval_s, self._refresh_alerts)
            self.run_worker(self._refresh_alerts(), exclusive=True, group="poll")
            # WebSocket consumer runs as a long-lived worker so the TUI
            # cancels it cleanly on App.exit().
            self.run_worker(
                self._consume_websocket(),
                exclusive=True,
                group="ws",
                start=True,
            )

        async def _refresh_alerts(self) -> None:
            items = await _poll_alerts(self._client)
            table = self.query_one("#alert-feed", DataTable)
            for alert in items:
                # The /api/v1/alerts response field is ``alert_id``; we accept
                # either ``alert_id`` or ``id`` so the TUI also works against
                # legacy / alternative serialisations.
                alert_id = str(alert.get("alert_id") or alert.get("id") or "")
                if not alert_id or alert_id in self._alerts_by_id:
                    continue
                self._alerts_by_id[alert_id] = alert
                ts_value = alert.get("timestamp_ns")
                # The schema may serialise large ints as strings (msgspec int64
                # safety). Coerce defensively before formatting.
                if isinstance(ts_value, str) and ts_value.isdigit():
                    ts_value = int(ts_value)
                table.add_row(
                    _format_ts(ts_value),
                    str(alert.get("severity", "")),
                    str(alert.get("alert_type", "")),
                    str(alert.get("rule_name", "")),
                    str(alert.get("entity_uuid", "")),
                    key=alert_id,
                )

        async def _consume_websocket(self) -> None:
            try:
                from websockets.asyncio.client import connect as _ws_connect
            except ImportError:
                _log.debug("tui: websockets not available; event stream disabled")
                return
            log = self.query_one("#event-stream", RichLog)
            try:
                async with _ws_connect(self._ws_url) as ws:

                    async def _iter_messages() -> Any:
                        async for raw in ws:
                            yield raw if isinstance(raw, str) else raw.decode("utf-8")

                    async def _on_event(payload: dict[str, Any]) -> None:
                        log.write(_format_event_line(payload))

                    await _consume_ws_messages(_iter_messages(), _on_event)
            except Exception as exc:
                _log.debug("tui: websocket loop ended: %s", type(exc).__name__)

        async def action_open_or_search(self) -> None:
            focused = self.focused
            if focused is None:
                return
            if isinstance(focused, Input):
                query = focused.value.strip()
                if not query:
                    return
                results = await _search_entities(self._client, query)
                table = self.query_one("#entity-search-results", DataTable)
                table.clear()
                for row in results:
                    table.add_row(
                        str(row.get("entity_type", "")),
                        str(row.get("entity_value", "")),
                        str(row.get("entity_uuid", "")),
                    )
                return
            if isinstance(focused, DataTable) and focused.id == "alert-feed":
                if focused.cursor_row < 0:
                    return
                row_key = focused.coordinate_to_cell_key(
                    focused.cursor_coordinate,
                ).row_key
                key = row_key.value if row_key is not None else None
                if key is None:
                    return
                alert = self._alerts_by_id.get(str(key))
                if alert is not None:
                    await self.push_screen(AlertDetailModal(alert))

    return SeerflowTUIApp


def __getattr__(name: str) -> Any:
    """PEP 562 lazy access to the Textual classes.

    Importing ``SeerflowTUIApp`` / ``AlertDetailModal`` from this module
    triggers the textual import — but only when the caller actually wants
    them. This keeps ``import seerflow.tui`` safe on systems without the
    optional extra.
    """
    if name in {"SeerflowTUIApp", "AlertDetailModal"}:
        if _load_textual() is None:
            raise ImportError("textual is not installed; install with 'pip install seerflow[tui]'")
        cls = _build_app_class()
        if name == "SeerflowTUIApp":
            return cls
        # AlertDetailModal lives inside the closure; rebuild it the same way.
        # The closure already produced both classes — _build_app_class returns
        # the App, the modal is reachable as a sibling via the textual import
        # graph. For symmetry, we re-import textual modules here and rebuild.
        return _build_alert_modal_class()
    raise AttributeError(f"module 'seerflow.tui' has no attribute {name!r}")


def _build_alert_modal_class() -> type[Any]:
    """Standalone construction of ``AlertDetailModal`` for ``__getattr__`` access."""
    from textual.binding import Binding
    from textual.screen import ModalScreen
    from textual.widgets import Static

    class AlertDetailModal(ModalScreen[None]):
        BINDINGS: ClassVar[list[Binding]] = [  # type: ignore[assignment]
            Binding("escape", "dismiss", "Close", show=True),
        ]

        def __init__(self, alert: dict[str, Any]) -> None:
            super().__init__()
            self._alert = alert

        def compose(self) -> Any:
            yield Static(
                json.dumps(self._alert, indent=2, sort_keys=True, default=str),
                id="alert-detail-body",
            )

        def action_dismiss(self) -> None:  # type: ignore[override]
            self.app.pop_screen()

    return AlertDetailModal


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_ts(ts_ns: object) -> str:
    """Format a nanosecond timestamp as ``HH:MM:SS`` (UTC)."""
    if not isinstance(ts_ns, int) or ts_ns <= 0:
        return ""
    seconds = ts_ns / 1_000_000_000
    return time.strftime("%H:%M:%S", time.gmtime(seconds))


def _format_event_line(payload: dict[str, Any]) -> str:
    """One-line summary of an event broadcast frame."""
    parts: list[str] = []
    ts = payload.get("timestamp_ns")
    if isinstance(ts, int):
        parts.append(_format_ts(ts))
    for key in ("severity", "source_type", "template", "message"):
        val = payload.get(key)
        if val is None or val == "":
            continue
        parts.append(f"{key}={val}")
    return " | ".join(parts) if parts else json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def launch_tui_with_pipeline(
    config: SeerflowConfig,
    *,
    _max_uptime_s: float | None = None,
) -> None:
    """Launch the Textual TUI alongside the running pipeline.

    Concurrency model: pipeline + uvicorn run as one task in an
    ``asyncio.TaskGroup``; the Textual app runs as the second task,
    gated on a warmup poll against ``/api/v1/health``. When either side
    exits the TaskGroup cancels the other, so SIGINT and ``q`` both
    converge on a clean shutdown via the existing ``_run_with_config``
    teardown path.

    On graceful textual absence (the optional extra is not installed),
    falls back to the plain pipeline path so the daemon still starts.
    The ``_max_uptime_s`` knob is for tests only — it caps the TUI
    runtime so an integration test never hangs the suite.
    """
    if _load_textual() is None:
        from seerflow.pipeline.run import _run_with_config

        await _run_with_config(config)
        return

    from seerflow.pipeline.run import _run_with_config

    host = config.health_bind_address
    port = config.dashboard_port
    base_url = f"http://{host}:{port}/api/v1"
    ws_url = f"ws://{host}:{port}/api/ws"

    async def _ui_after_warmup() -> None:
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=_DEFAULT_HTTP_TIMEOUT_S,
        ) as client:
            await _warmup(client)
            app_cls = _build_app_class()
            app = app_cls(client=client, ws_url=ws_url)
            if _max_uptime_s is not None:
                # Test-only hard cap so the integration suite never hangs.
                async def _auto_quit() -> None:
                    await asyncio.sleep(_max_uptime_s)
                    app.exit(0)

                asyncio.create_task(_auto_quit())  # noqa: RUF006
            await app.run_async()

    async with asyncio.TaskGroup() as tg:
        pipeline_task = tg.create_task(_run_with_config(config))
        ui_task = tg.create_task(_ui_after_warmup())

        async def _on_ui_exit() -> None:
            try:
                await ui_task
            finally:
                # When the operator quits the TUI, tear the pipeline down.
                if not pipeline_task.done():
                    pipeline_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pipeline_task

        tg.create_task(_on_ui_exit())


__all__ = [
    "launch_tui_with_pipeline",
]
