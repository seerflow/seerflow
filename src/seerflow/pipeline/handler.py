"""Event handler factory for the Seerflow pipeline."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import msgspec.structs

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.receivers.base import RawEvent
    from seerflow.sigma.engine import SigmaEngine
    from seerflow.storage.sqlite import SqliteBackend

_log = logging.getLogger("seerflow")


def _make_handler(
    ensemble: DetectionEnsemble,
    storage: SqliteBackend,
    save_interval_ns: int = 300_000_000_000,
    sigma_engine: SigmaEngine | None = None,
) -> Callable[[RawEvent], Awaitable[None]]:
    """Create an event handler that runs detection and persists events."""
    from seerflow.models.alert import create_ml_alert
    from seerflow.parsing import EventNormalizer
    from seerflow.storage.sqlite import TemplateInfo

    normalizer = EventNormalizer()
    event_count = 0
    anomaly_count = 0
    template_meta: dict[int, TemplateInfo] = {}
    start_time = time.time()
    last_save_ns = time.time_ns()

    async def handler(event: RawEvent) -> None:
        nonlocal event_count, anomaly_count, last_save_ns
        seerflow_event = normalizer.normalize(event)

        # Derive entity_refs for HST entity_count + storage compatibility
        entity_refs = (
            seerflow_event.related_ips
            + seerflow_event.related_users
            + seerflow_event.related_hosts
        )
        if entity_refs:
            seerflow_event = msgspec.structs.replace(
                seerflow_event,
                entity_refs=entity_refs,
            )

        # Track template metadata
        if seerflow_event.template_id != -1:
            if seerflow_event.template_id not in template_meta:
                _log.info(
                    "New template discovered: [%d] %s",
                    seerflow_event.template_id,
                    seerflow_event.template_str[:120],
                )
                template_meta[seerflow_event.template_id] = TemplateInfo(
                    template_id=seerflow_event.template_id,
                    template_str=seerflow_event.template_str,
                    first_seen_ns=event.received_ns,
                    last_seen_ns=event.received_ns,
                    event_count=1,
                    example_message=seerflow_event.message[:500],
                )
            else:
                existing = template_meta[seerflow_event.template_id]
                template_meta[seerflow_event.template_id] = TemplateInfo(
                    template_id=seerflow_event.template_id,
                    template_str=seerflow_event.template_str,
                    first_seen_ns=existing.first_seen_ns,
                    last_seen_ns=event.received_ns,
                    event_count=existing.event_count + 1,
                    example_message=existing.example_message,
                )

        # Persist to storage (WriteBuffer handles batching + 100ms timer flush)
        await storage.write_events([seerflow_event])

        result = ensemble.process_event(seerflow_event)
        event_count += 1

        # Flush template metadata every 10 events
        if event_count % 10 == 0 and template_meta:
            pending = list(template_meta.values())
            await storage.write_templates(pending)
            # Reset counts only after successful write
            for tid in template_meta:
                t = template_meta[tid]
                template_meta[tid] = TemplateInfo(
                    template_id=t.template_id,
                    template_str=t.template_str,
                    first_seen_ns=t.first_seen_ns,
                    last_seen_ns=t.last_seen_ns,
                    event_count=0,
                    example_message=t.example_message,
                )

        _log.debug(
            "event tid=%d entities=%d score=%.4f thresh=%.4f src=%s",
            seerflow_event.template_id,
            len(entity_refs),
            result.score,
            result.upper_threshold,
            event.source_type,
        )

        if result.is_anomaly:
            anomaly_count += 1
            _log.warning(
                "ANOMALY [%s] score=%.3f threshold=%.3f dir=%s",
                result.source_type,
                result.score,
                result.upper_threshold,
                result.anomaly_direction,
            )
            _log.warning(
                "  template: [%d] %s",
                seerflow_event.template_id,
                seerflow_event.template_str[:120],
            )
            _log.warning(
                "  message:  %s",
                seerflow_event.message[:200],
            )
            if entity_refs:
                _log.warning(
                    "  entities: %s",
                    ", ".join(entity_refs[:10]),
                )
            alert = create_ml_alert(seerflow_event, result)
            try:
                await storage.write_alert(alert)
            except Exception:
                _log.warning("Alert write failed", exc_info=True)

        # Sigma rule evaluation
        if sigma_engine is not None:
            try:
                sigma_alerts = sigma_engine.evaluate(seerflow_event)
                for sigma_alert in sigma_alerts:
                    try:
                        await storage.write_alert(sigma_alert)
                    except Exception:
                        _log.warning("Sigma alert write failed", exc_info=True)
            except Exception:
                _log.warning("Sigma evaluation failed", exc_info=True)

        # Periodic model state save
        if event_count % 100 == 0 and event_count > 0:
            now_ns = time.time_ns()
            if now_ns - last_save_ns >= save_interval_ns:
                try:
                    saved = await ensemble.save_all_state(storage)
                    _log.info("Periodic save: %d model states", saved)
                    last_save_ns = now_ns
                except Exception:
                    _log.warning(
                        "Periodic model save failed — will retry",
                        exc_info=True,
                    )

    handler.get_stats = lambda: (event_count, anomaly_count, template_meta, start_time)  # type: ignore[attr-defined]
    return handler
