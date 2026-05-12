"""Shared fakes for S-071 service / endpoint tests.

Used by ``tests/unit/llm/explanation/test_service.py`` and
``tests/integration/test_explanation_endpoint.py`` (re-imported via a
module-relative path).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent
from seerflow.models.query import Page

if TYPE_CHECKING:
    from seerflow.models.query import AlertQuery, EventQuery


_CANNED_RESPONSE = (
    "SUMMARY: Anomalous login from new IP.\n"
    "RATIONALE: First login at this hour for this user.\n"
    "EVENTS:\n"
    "- 03:14 ssh from 10.0.0.1\n"
    "NEXT STEPS:\n"
    "- Reset alice's password\n"
)


class FakeLLMBackend:
    """In-memory backend with configurable canned response / exceptions."""

    name = "fake_llm"

    def __init__(
        self,
        *,
        response: str = _CANNED_RESPONSE,
        raise_exc: BaseException | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self._response = response
        self._raise_exc = raise_exc
        self._delay_s = delay_s
        self.call_count = 0
        self.last_args: dict[str, object] | None = None

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: tuple[str, ...] = (),
    ) -> str:
        self.call_count += 1
        self.last_args = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stop": stop,
        }
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


class FakeAlertStore:
    """In-memory alert lookup. Only ``get_alert_by_id`` is exercised."""

    def __init__(self, alerts: tuple[Alert, ...] = ()) -> None:
        self._by_id = {a.alert_id: a for a in alerts}

    async def get_alert_by_id(self, alert_id: str) -> Alert | None:
        return self._by_id.get(alert_id)

    # The remaining ``AlertStore`` Protocol methods are intentionally absent;
    # callers in S-071 only need ``get_alert_by_id``.

    async def write_alert(self, alert: Alert) -> None:  # pragma: no cover - unused
        self._by_id[alert.alert_id] = alert

    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]:  # pragma: no cover - unused
        items = tuple(self._by_id.values())
        return Page(items=items, total=len(items), page=1, limit=len(items))


class FakeLogStore:
    """In-memory event store returning a static ``Page``."""

    def __init__(self, events: tuple[SeerflowEvent, ...] = ()) -> None:
        self._events = events
        self.query_calls = 0

    async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]:
        self.query_calls += 1
        return Page(
            items=self._events,
            total=len(self._events),
            page=filters.page,
            limit=filters.limit,
        )

    async def write_events(self, events: list[SeerflowEvent]) -> None:  # pragma: no cover
        self._events = (*self._events, *events)

    async def flush(self) -> None:  # pragma: no cover
        return None


def make_alert(
    *,
    alert_id: str = "11111111-1111-1111-1111-111111111111",
    entity_uuid: str = "22222222-2222-2222-2222-222222222222",
    contributing_events: tuple[uuid.UUID, ...] = (
        uuid.UUID("33333333-3333-3333-3333-333333333333"),
    ),
) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type="ml",
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=4,
        rule_name="rule.x",
        description="Test alert",
        entity_uuid=entity_uuid,
        entity_value="alice",
        entity_type="user",
        contributing_events=contributing_events,
        mitre_tactics=("TA0001",),
        mitre_techniques=("T1078",),
        risk_score=0.87,
    )


_DEFAULT_EVENT_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def make_event(
    event_id: uuid.UUID | None = None,
    message: str = "ssh login from 10.0.0.1",
    timestamp_ns: int = 1_700_000_000_000_000_000,
) -> SeerflowEvent:
    if event_id is None:
        event_id = _DEFAULT_EVENT_ID
    return SeerflowEvent(
        event_id=event_id,
        timestamp_ns=timestamp_ns,
        observed_ns=timestamp_ns,
        message=message,
        source_type="auth",
    )
