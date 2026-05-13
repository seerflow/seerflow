"""Unit tests for ``seerflow hunt`` CLI command (S-072, FR-057)."""

from __future__ import annotations

import argparse
import json
import uuid
from typing import Any
from unittest.mock import patch

import pytest

from seerflow import hunt_cmd
from seerflow.llm.hunt.result import HuntResult
from seerflow.models.event import SeerflowEvent


def _event() -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        message="ssh login from 10.0.0.1",
        source_type="auth",
    )


def _args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "query": "ssh logins",
        "limit": None,
        "db": None,
        "json": False,
        "config": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class _FakeService:
    def __init__(
        self,
        *,
        result: HuntResult | None = None,
        raise_exc: BaseException | None = None,
    ) -> None:
        self._result = result
        self._raise_exc = raise_exc
        self.call_count = 0

    async def hunt(self, nl_query: str) -> HuntResult:
        self.call_count += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._result is None:
            return HuntResult(
                query=nl_query,
                filters={"text_query": nl_query},
                events=(_event(),),
                total=1,
                model="fake_llm",
                generated_at_ns=0,
                latency_ms=1.5,
                cached=False,
                truncated=False,
            )
        return self._result


@pytest.mark.unit
async def test_run_hunt_prints_table_on_happy_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    svc = _FakeService()
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (svc, _FakeCloseable())
        rc = await hunt_cmd.run_hunt(_args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "ssh login from 10.0.0.1" in out
    # Filters echoed back.
    assert "text_query" in out or "filters" in out


@pytest.mark.unit
async def test_run_hunt_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    svc = _FakeService()
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (svc, _FakeCloseable())
        rc = await hunt_cmd.run_hunt(_args(json=True))
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["query"] == "ssh logins"
    assert "filters" in payload
    assert isinstance(payload["events"], list)
    assert len(payload["events"]) == 1


@pytest.mark.unit
async def test_run_hunt_fallback_when_llm_disabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (None, _FakeCloseable())
        rc = await hunt_cmd.run_hunt(_args())
    assert rc == 0
    err = capsys.readouterr().err
    assert "seerflow query events" in err


@pytest.mark.unit
async def test_run_hunt_value_error_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    svc = _FakeService(raise_exc=ValueError("nl_query must be non-empty"))
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (svc, _FakeCloseable())
        rc = await hunt_cmd.run_hunt(_args(query="  "))
    assert rc != 0
    err = capsys.readouterr().err
    assert "non-empty" in err


@pytest.mark.unit
async def test_run_hunt_runtime_error_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    svc = _FakeService(raise_exc=RuntimeError("backend died"))
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (svc, _FakeCloseable())
        rc = await hunt_cmd.run_hunt(_args())
    assert rc != 0
    err = capsys.readouterr().err
    assert "backend died" in err or "Error" in err


class _FakeCloseable:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.unit
async def test_run_hunt_table_handles_empty_results(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = HuntResult(
        query="ssh",
        filters={"text_query": "ssh"},
        events=(),
        total=0,
        model="fake_llm",
        generated_at_ns=0,
        latency_ms=0.0,
        cached=False,
        truncated=False,
    )
    svc = _FakeService(result=result)
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (svc, _FakeCloseable())
        rc = await hunt_cmd.run_hunt(_args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "No events found." in out


@pytest.mark.unit
async def test_build_service_and_storage_returns_none_when_llm_disabled(
    tmp_path: Any,
) -> None:
    """Builder returns ``(None, storage)`` when ``build_llm_backend`` returns None."""
    fake_storage = _FakeCloseable()

    async def fake_connect_storage(_cfg: Any) -> Any:
        return fake_storage

    def fake_build_llm(_cfg: Any) -> Any:
        return None

    args = _args()
    with (
        patch.object(hunt_cmd, "connect_storage", fake_connect_storage),
        patch.object(hunt_cmd, "build_llm_backend", fake_build_llm),
    ):
        service, storage = await hunt_cmd._build_service_and_storage(args)
    assert service is None
    assert storage is fake_storage


@pytest.mark.unit
async def test_build_service_and_storage_returns_service_when_llm_ready(
    tmp_path: Any,
) -> None:
    """Builder constructs a real service when the backend is available."""
    fake_storage = _FakeCloseable()

    class _Backend:
        name = "fake_llm"

        async def complete(self, *_a: Any, **_kw: Any) -> str:
            return ""

    async def fake_connect_storage(_cfg: Any) -> Any:
        return fake_storage

    def fake_build_llm(_cfg: Any) -> Any:
        return _Backend()

    args = _args()
    with (
        patch.object(hunt_cmd, "connect_storage", fake_connect_storage),
        patch.object(hunt_cmd, "build_llm_backend", fake_build_llm),
    ):
        service, storage = await hunt_cmd._build_service_and_storage(args)
    assert service is not None
    assert storage is fake_storage


# ---------------------------------------------------------------------------
# S-076: entity-mode routing tests
# ---------------------------------------------------------------------------


class _FakeStorage:
    """Minimal storage stub for entity-mode tests."""

    def __init__(self, events: tuple[SeerflowEvent, ...]) -> None:
        self._events = events
        self.last_query: Any = None
        self.closed = False

    async def query_events(self, query: Any) -> Any:
        self.last_query = query
        from seerflow.models.query import Page

        return Page(items=self._events, total=len(self._events), page=1, limit=query.limit)

    async def close(self) -> None:
        self.closed = True


def _ip_event() -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        message="connection from 10.0.0.5",
        source_type="auth",
    )


@pytest.mark.unit
async def test_run_hunt_entity_ip_path_skips_llm(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When query is an IP, entity path runs; service.hunt is never called."""
    svc = _FakeService()
    storage = _FakeStorage((_ip_event(),))
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (svc, storage)
        rc = await hunt_cmd.run_hunt(_args(query="10.0.0.5"))
    assert rc == 0
    assert svc.call_count == 0
    out = capsys.readouterr().out
    assert "entity" in out
    assert "10.0.0.5" in out


@pytest.mark.unit
async def test_run_hunt_entity_uuid_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A UUID-shaped query routes via entity path."""
    svc = _FakeService()
    storage = _FakeStorage((_ip_event(),))
    target = str(uuid.uuid4())
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (svc, storage)
        rc = await hunt_cmd.run_hunt(_args(query=target))
    assert rc == 0
    assert svc.call_count == 0
    assert storage.last_query is not None
    assert storage.last_query.entity_uuid == target


@pytest.mark.unit
async def test_run_hunt_entity_when_llm_disabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Entity path runs even when LLM backend is unavailable."""
    storage = _FakeStorage((_ip_event(),))
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (None, storage)
        rc = await hunt_cmd.run_hunt(_args(query="10.0.0.5"))
    assert rc == 0
    out = capsys.readouterr().out
    err = capsys.readouterr().err
    # No fallback message — entity path served it.
    assert "seerflow query events" not in err
    assert "entity" in out
    assert "10.0.0.5" in out


@pytest.mark.unit
async def test_run_hunt_entity_json_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Entity-mode JSON output includes mode + entity_uuid in filters."""
    storage = _FakeStorage((_ip_event(),))
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (None, storage)
        rc = await hunt_cmd.run_hunt(_args(query="10.0.0.5", json=True))
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["filters"]["mode"] == "entity"
    assert payload["filters"]["entity_type"] == "ip"
    assert payload["filters"]["entity_value"] == "10.0.0.5"
    assert "entity_uuid" in payload["filters"]


@pytest.mark.unit
async def test_run_hunt_free_text_still_goes_to_llm(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A free-text multi-word query bypasses entity detection."""
    svc = _FakeService()
    storage = _FakeStorage(())
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (svc, storage)
        rc = await hunt_cmd.run_hunt(_args(query="failed login attempts"))
    assert rc == 0
    assert svc.call_count == 1
    # Storage entity path was NOT invoked.
    assert storage.last_query is None


class _FailingStorage:
    """Storage stub that raises on query_events. Used for entity error paths."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.closed = False

    async def query_events(self, _query: Any) -> Any:
        raise self._exc

    async def close(self) -> None:
        self.closed = True


@pytest.mark.unit
async def test_run_hunt_entity_storage_exception_returns_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A storage exception during entity hunt returns exit code 1."""
    storage = _FailingStorage(RuntimeError("db gone"))
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (None, storage)
        rc = await hunt_cmd.run_hunt(_args(query="10.0.0.5"))
    assert rc == 1
    err = capsys.readouterr().err
    assert "db gone" in err or "Error" in err


@pytest.mark.unit
async def test_run_hunt_entity_invalid_limit_returns_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An out-of-range ``--limit`` triggers EventQuery validation → exit 2."""
    storage = _FakeStorage(())
    with patch.object(hunt_cmd, "_build_service_and_storage") as builder:
        builder.return_value = (None, storage)
        rc = await hunt_cmd.run_hunt(_args(query="10.0.0.5", limit=999999))
    assert rc == 2
    err = capsys.readouterr().err
    assert "limit" in err.lower() or "Error" in err
