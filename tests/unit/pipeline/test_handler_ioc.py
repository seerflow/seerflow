"""Unit tests for the IoC enrichment block in pipeline.handler (S-069)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.models.indicator import Indicator
from seerflow.models.ioc_match import IoCMatch
from seerflow.pipeline.handler import make_handler
from seerflow.receivers.base import RawEvent
from seerflow.threat_intel.enricher import _IoCEnrichmentCounters


@dataclass
class _FakeMatcher:
    matches: tuple[IoCMatch, ...] = ()
    calls: list[Any] = field(default_factory=list)

    def check_event(self, event: Any) -> tuple[IoCMatch, ...]:
        self.calls.append(event)
        return tuple(
            IoCMatch(
                value=m.value,
                type=m.type,
                indicator=m.indicator,
                event_id=str(event.event_id),
                entity_kind=m.entity_kind,
                matched_at_ns=m.matched_at_ns,
            )
            for m in self.matches
        )


def _ind() -> Indicator:
    return Indicator(
        value="1.2.3.4",
        type="ipv4",
        source_feed="otx",
        confidence=75,
        kill_chain_phases=("command-and-control",),
        valid_from_ns=0,
        valid_until_ns=None,
    )


def _seed_match() -> IoCMatch:
    return IoCMatch(
        value="1.2.3.4",
        type="ipv4",
        indicator=_ind(),
        event_id="placeholder",
        entity_kind="ip",
        matched_at_ns=1,
    )


def _raw_event() -> RawEvent:
    return RawEvent(
        data=b"probe from 1.2.3.4",
        source_type="syslog",
        source_id="syslog-test",
        received_ns=1_700_000_000_000_000_000,
        metadata={},
    )


def _ensemble_mock() -> MagicMock:
    ensemble = MagicMock()
    ensemble.process_event = MagicMock(
        return_value=MagicMock(
            score=0.0,
            is_anomaly=False,
            upper_threshold=1.0,
            anomaly_direction="up",
            source_type="syslog",
        )
    )
    return ensemble


@pytest.mark.asyncio
async def test_handler_writes_ioc_alert_and_enriches_event() -> None:
    storage = MagicMock()
    storage.write_alert = AsyncMock(return_value=True)
    storage.write_events = AsyncMock()
    storage.write_templates = AsyncMock()
    storage.write_edge = AsyncMock()

    matcher = _FakeMatcher(matches=(_seed_match(),))
    counters = _IoCEnrichmentCounters()

    handler = make_handler(
        ensemble=_ensemble_mock(),
        storage=storage,
        ioc_matcher=matcher,
        ioc_enrichment_counters=counters,
    )

    await handler(_raw_event())

    storage.write_alert.assert_awaited_once()
    alert = storage.write_alert.call_args.args[0]
    assert alert.alert_type == "ioc"
    assert alert.rule_name == "ti:otx"
    storage.write_events.assert_awaited_once()
    persisted = storage.write_events.call_args.args[0][0]
    assert persisted.attributes["ioc_matches"][0]["value"] == "1.2.3.4"
    assert counters.alerts_emitted_total == 1


@pytest.mark.asyncio
async def test_handler_skips_when_matcher_none() -> None:
    storage = MagicMock()
    storage.write_alert = AsyncMock(return_value=True)
    storage.write_events = AsyncMock()
    storage.write_templates = AsyncMock()
    storage.write_edge = AsyncMock()

    handler = make_handler(
        ensemble=_ensemble_mock(),
        storage=storage,
        ioc_matcher=None,
    )
    await handler(_raw_event())

    storage.write_alert.assert_not_called()
    storage.write_events.assert_awaited_once()
    persisted = storage.write_events.call_args.args[0][0]
    assert "ioc_matches" not in persisted.attributes


@pytest.mark.asyncio
async def test_handler_skips_when_dedup_returns_false() -> None:
    storage = MagicMock()
    storage.write_alert = AsyncMock(return_value=False)  # dedup hit
    storage.write_events = AsyncMock()
    storage.write_templates = AsyncMock()
    storage.write_edge = AsyncMock()
    dispatcher = MagicMock()
    counters = _IoCEnrichmentCounters()

    handler = make_handler(
        ensemble=_ensemble_mock(),
        storage=storage,
        ioc_matcher=_FakeMatcher(matches=(_seed_match(),)),
        ioc_enrichment_counters=counters,
        alert_dispatcher=dispatcher,
    )

    await handler(_raw_event())

    dispatcher.enqueue.assert_not_called()
    assert counters.alerts_deduped_total == 1
