"""Unit tests for ``seerflow.web.middleware`` (S-225 / SEE-248).

Asserts the ASGI-level contract of ``CollapseSlashesMiddleware``:

* HTTP scopes with runs of ``/`` in ``path`` get collapsed to a single
  ``/`` and ``raw_path`` is rewritten to match (UTF-8 bytes).
* Already-canonical HTTP paths pass through untouched.
* Non-HTTP scopes (``websocket``, ``lifespan``) are not modified.
* The caller's scope dict is never mutated in place — the middleware
  builds a new dict, per the project immutability rule.

These tests run at the raw ASGI layer (no FastAPI / TestClient) so the
behaviour is exercised independently of route dispatch and any
upstream URL canonicalisation that ``httpx`` performs in
``test_static.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from seerflow.web.middleware import CollapseSlashesMiddleware

Scope = dict[str, Any]
Captured = dict[str, Any]


@pytest.fixture
def captured() -> Captured:
    """Bag the dummy ASGI app writes the received scope into."""
    return {}


@pytest.fixture
def middleware(captured: Captured) -> CollapseSlashesMiddleware:
    async def _app(
        scope: Scope,
        receive: Callable[[], Awaitable[Any]],
        send: Callable[[Any], Awaitable[None]],
    ) -> None:
        captured["scope"] = scope

    return CollapseSlashesMiddleware(_app)


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _noop_send(_message: Any) -> None:
    return None


async def test_collapses_leading_double_slash(
    middleware: CollapseSlashesMiddleware, captured: Captured
) -> None:
    scope: Scope = {"type": "http", "path": "//api/v1/x", "raw_path": b"//api/v1/x"}
    await middleware(scope, _noop_receive, _noop_send)
    received: Scope = captured["scope"]
    assert received["path"] == "/api/v1/x"
    assert received["raw_path"] == b"/api/v1/x"


async def test_collapses_runs_of_three_or_more(
    middleware: CollapseSlashesMiddleware, captured: Captured
) -> None:
    scope: Scope = {
        "type": "http",
        "path": "///foo/bar//baz",
        "raw_path": b"///foo/bar//baz",
    }
    await middleware(scope, _noop_receive, _noop_send)
    received: Scope = captured["scope"]
    assert received["path"] == "/foo/bar/baz"
    assert received["raw_path"] == b"/foo/bar/baz"


async def test_canonical_path_passes_through_unchanged(
    middleware: CollapseSlashesMiddleware, captured: Captured
) -> None:
    scope: Scope = {
        "type": "http",
        "path": "/already/canonical",
        "raw_path": b"/already/canonical",
    }
    await middleware(scope, _noop_receive, _noop_send)
    received: Scope = captured["scope"]
    assert received["path"] == "/already/canonical"
    assert received["raw_path"] == b"/already/canonical"


async def test_websocket_scope_not_modified(
    middleware: CollapseSlashesMiddleware, captured: Captured
) -> None:
    scope: Scope = {
        "type": "websocket",
        "path": "//api/v1/ws",
        "raw_path": b"//api/v1/ws",
    }
    await middleware(scope, _noop_receive, _noop_send)
    received: Scope = captured["scope"]
    # Middleware must not touch non-HTTP scopes — WS handshakes carry
    # their own path semantics and are dispatched by a different
    # router that does not share the SPA mount.
    assert received["path"] == "//api/v1/ws"
    assert received["raw_path"] == b"//api/v1/ws"


async def test_lifespan_scope_not_modified(
    middleware: CollapseSlashesMiddleware, captured: Captured
) -> None:
    scope: Scope = {"type": "lifespan"}
    await middleware(scope, _noop_receive, _noop_send)
    received: Scope = captured["scope"]
    assert received == {"type": "lifespan"}


async def test_other_scope_fields_preserved(
    middleware: CollapseSlashesMiddleware, captured: Captured
) -> None:
    scope: Scope = {
        "type": "http",
        "path": "//api/v1/x",
        "raw_path": b"//api/v1/x",
        "method": "GET",
        "query_string": b"a=1&b=2",
        "headers": [(b"host", b"example.test")],
    }
    await middleware(scope, _noop_receive, _noop_send)
    received: Scope = captured["scope"]
    assert received["method"] == "GET"
    assert received["query_string"] == b"a=1&b=2"
    assert received["headers"] == [(b"host", b"example.test")]


async def test_does_not_mutate_input_scope(
    middleware: CollapseSlashesMiddleware, captured: Captured
) -> None:
    scope: Scope = {"type": "http", "path": "//api/v1/x", "raw_path": b"//api/v1/x"}
    original_id = id(scope)
    await middleware(scope, _noop_receive, _noop_send)
    # Caller's dict must be untouched (immutability rule).
    assert scope["path"] == "//api/v1/x"
    assert scope["raw_path"] == b"//api/v1/x"
    assert id(scope) == original_id


async def test_canonical_http_scope_passes_same_dict_object(
    middleware: CollapseSlashesMiddleware, captured: Captured
) -> None:
    """Zero-cost happy path: no ``//`` in the path → no copy of scope."""
    scope: Scope = {"type": "http", "path": "/api/v1/x", "raw_path": b"/api/v1/x"}
    await middleware(scope, _noop_receive, _noop_send)
    received: Scope = captured["scope"]
    assert received is scope
