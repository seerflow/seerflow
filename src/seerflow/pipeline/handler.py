"""Event handler factory for the Seerflow pipeline."""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING

import msgspec.structs

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from seerflow.correlation.engine import CorrelationEngine
    from seerflow.correlation.holders import EngineHolder
    from seerflow.correlation.risk import RiskRegister
    from seerflow.correlation.watermark import Watermark
    from seerflow.correlation.window import EntityWindowBuffer
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.graph.entity_graph import EntityGraph
    from seerflow.receivers.base import RawEvent
    from seerflow.sigma.engine import SigmaEngine
    from seerflow.storage.sqlite import SqliteBackend

_log = logging.getLogger("seerflow")


def _make_handler(
    ensemble: DetectionEnsemble,
    storage: SqliteBackend,
    save_interval_ns: int = 300_000_000_000,
    sigma_holder: EngineHolder[SigmaEngine | None] | None = None,
    entity_graph: EntityGraph | None = None,
    graph_algo_interval: int = 500,
    window_buffer: EntityWindowBuffer | None = None,
    watermark: Watermark | None = None,
    risk_register: RiskRegister | None = None,
    correlation_holder: EngineHolder[CorrelationEngine | None] | None = None,
) -> Callable[[RawEvent], Awaitable[None]]:
    """Create an event handler that runs detection and persists events."""
    from seerflow.graph.edges import infer_edges
    from seerflow.models.alert import create_ml_alerts
    from seerflow.models.entity import resolve_entities, sanitize_for_log
    from seerflow.parsing import EventNormalizer
    from seerflow.storage.sqlite import TemplateInfo

    normalizer = EventNormalizer()
    event_count = 0
    anomaly_count = 0
    template_meta: dict[int, TemplateInfo] = {}
    start_time = time.time()
    last_save_ns = time.time_ns()
    risk_alerted: set[str] = set()  # entities that already fired a risk alert

    async def handler(event: RawEvent) -> None:
        nonlocal event_count, anomaly_count, last_save_ns
        seerflow_event = normalizer.normalize(event)

        # Resolve entities to deterministic UUID5 strings.
        # Resolve each type separately to build both entity_refs (flat tuple
        # for correlation/risk) and typed_for_edges (typed pairs for edge
        # inference) in a single pass.
        typed_for_edges: list[tuple[str, str]] = []
        entity_refs_list: list[str] = []
        for _type_name, _raw_vals, _ips, _users, _hosts, _kw in (
            (
                "ip",
                seerflow_event.related_ips,
                seerflow_event.related_ips,
                (),
                (),
                {},
            ),
            (
                "user",
                seerflow_event.related_users,
                (),
                seerflow_event.related_users,
                (),
                {},
            ),
            (
                "host",
                seerflow_event.related_hosts,
                (),
                (),
                seerflow_event.related_hosts,
                {},
            ),
            (
                "domain",
                seerflow_event.related_domains,
                (),
                (),
                (),
                {"domains": seerflow_event.related_domains},
            ),
            (
                "file",
                seerflow_event.related_files,
                (),
                (),
                (),
                {"files": seerflow_event.related_files},
            ),
            (
                "process",
                seerflow_event.related_processes,
                (),
                (),
                (),
                {"processes": seerflow_event.related_processes},
            ),
        ):
            if _raw_vals:
                for _uid in resolve_entities(_ips, _users, _hosts, **_kw):
                    typed_for_edges.append((_type_name, _uid))
                    entity_refs_list.append(_uid)
        entity_refs = tuple(entity_refs_list)
        if entity_refs:
            seerflow_event = msgspec.structs.replace(
                seerflow_event,
                entity_refs=entity_refs,
            )

        # Advance watermark and check for late events
        if watermark is not None:
            watermark.advance(seerflow_event.timestamp_ns)

        # Add event to correlation window buffer for each entity
        if window_buffer is not None and entity_refs:
            # Skip late events for correlation (still stored + ML-scored)
            if watermark is not None and watermark.is_late(seerflow_event.timestamp_ns):
                _log.debug(
                    "Late event skipped for correlation: ts=%d watermark=%d",
                    seerflow_event.timestamp_ns,
                    watermark.current_ns,
                )
            else:
                for entity_uuid in entity_refs:
                    window_buffer.add_event(entity_uuid, seerflow_event)

        # Evaluate correlation rules (skip late events)
        is_late = watermark is not None and watermark.is_late(seerflow_event.timestamp_ns)
        correlation_engine = correlation_holder.engine if correlation_holder is not None else None
        if correlation_engine is not None and entity_refs and not is_late:
            try:
                corr_alerts = correlation_engine.evaluate(seerflow_event, entity_refs)
                for corr_alert in corr_alerts:
                    try:
                        await storage.write_alert(corr_alert)
                    except Exception:
                        _log.warning("Correlation alert write failed", exc_info=True)

                    # Feed correlation alerts into risk register
                    if risk_register is not None and corr_alert.entity_uuid:
                        from seerflow.correlation.risk import RiskEntry

                        risk_entry = RiskEntry(
                            timestamp_ns=seerflow_event.timestamp_ns,
                            risk_points=corr_alert.risk_score * 20,
                            source="correlation",
                            rule_name=corr_alert.rule_name,
                            mitre_tactics=corr_alert.mitre_tactics,
                            mitre_techniques=corr_alert.mitre_techniques,
                        )
                        risk_register.add_risk(corr_alert.entity_uuid, risk_entry)
            except Exception:
                _log.warning("Correlation evaluation failed", exc_info=True)

        # Update entity graph with inferred edges
        if entity_graph is not None and typed_for_edges:
            edges = infer_edges(typed_for_edges)
            for edge in edges:
                entity_graph.add_edge(
                    edge.source_id,
                    edge.target_id,
                    edge.rel_type,
                    event.received_ns,
                )
                try:
                    await storage.write_edge(
                        edge.source_id,
                        edge.target_id,
                        edge.rel_type,
                        event.received_ns,
                    )
                except Exception:
                    _log.warning("Graph edge write failed", exc_info=True)

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
            _log.debug(
                "  message:  %s",
                seerflow_event.message[:200],
            )

            # Type-prefixed entity logging for safe, structured triage.
            # Escape control chars to prevent log injection from crafted input.
            entity_parts: list[str] = []
            for label, vals in (
                ("IPs", seerflow_event.related_ips),
                ("Users", seerflow_event.related_users),
                ("Hosts", seerflow_event.related_hosts),
                ("Domains", seerflow_event.related_domains),
                ("Files", seerflow_event.related_files),
                ("Processes", seerflow_event.related_processes),
            ):
                if vals:
                    entity_parts.append(
                        f"{label}: {', '.join(sanitize_for_log(v) for v in vals[:5])}"
                    )
            if entity_parts:
                _log.warning("  entities: %s", ", ".join(entity_parts))
            alerts = create_ml_alerts(seerflow_event, result, typed_for_edges)
            for alert in alerts:
                try:
                    await storage.write_alert(alert)
                except Exception:
                    _log.warning("Alert write failed", exc_info=True)

            # Add risk for ML anomaly
            if risk_register is not None and entity_refs:
                from seerflow.correlation.risk import RiskEntry

                for entity_uuid in entity_refs:
                    risk_entry = RiskEntry(
                        timestamp_ns=seerflow_event.timestamp_ns,
                        risk_points=result.score * 10,
                        source="ml",
                        rule_name="hst-anomaly",
                        mitre_tactics=(),
                        mitre_techniques=(),
                    )
                    risk_register.add_risk(entity_uuid, risk_entry)

        # Sigma rule evaluation
        sigma_engine = sigma_holder.engine if sigma_holder is not None else None
        if sigma_engine is not None:
            try:
                sigma_alerts = sigma_engine.evaluate(seerflow_event)
                for sigma_alert in sigma_alerts:
                    try:
                        await storage.write_alert(sigma_alert)
                    except Exception:
                        _log.warning("Sigma alert write failed", exc_info=True)

                    # Add risk for Sigma match
                    if risk_register is not None and entity_refs:
                        from seerflow.correlation.risk import RiskEntry

                        for entity_uuid in entity_refs:
                            risk_entry = RiskEntry(
                                timestamp_ns=seerflow_event.timestamp_ns,
                                risk_points=(15.0 if sigma_alert.severity_id.value >= 4 else 5.0),
                                source="sigma",
                                rule_name=sigma_alert.rule_name,
                                mitre_tactics=sigma_alert.mitre_tactics,
                                mitre_techniques=sigma_alert.mitre_techniques,
                            )
                            risk_register.add_risk(entity_uuid, risk_entry)
            except Exception:
                _log.warning("Sigma evaluation failed", exc_info=True)

        # Check risk threshold and fire correlation alert (with cooldown)
        if risk_register is not None and entity_refs:
            from seerflow.models.alert import Alert
            from seerflow.models.entity import infer_entity_type, primary_entity_value

            for entity_uuid in entity_refs:
                if entity_uuid in risk_alerted:
                    continue  # Already alerted for this entity
                if risk_register.check_threshold(entity_uuid):
                    risk_alerted.add(entity_uuid)
                    risk_score = risk_register.get_risk(entity_uuid)
                    risk_alert = Alert(
                        alert_id=str(
                            uuid.uuid5(
                                uuid.NAMESPACE_DNS,
                                f"risk:{entity_uuid}:{seerflow_event.timestamp_ns}",
                            )
                        ),
                        alert_type="correlation",
                        timestamp_ns=seerflow_event.timestamp_ns,
                        severity_id=seerflow_event.severity_id,
                        rule_name="risk-accumulation",
                        description=(f"Entity risk threshold exceeded: score={risk_score:.1f}"),
                        entity_uuid=entity_uuid,
                        entity_value=primary_entity_value(seerflow_event),
                        entity_type=infer_entity_type(seerflow_event),
                        contributing_events=(seerflow_event.event_id,),
                        risk_score=risk_score,
                        dedup_key=f"risk:{entity_uuid}",
                    )
                    try:
                        await storage.write_alert(risk_alert)
                    except Exception:
                        _log.warning("Risk alert write failed", exc_info=True)

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

        # Run graph algorithms periodically
        if entity_graph is not None and entity_graph.vertex_count > 0:
            try:
                if event_count % graph_algo_interval == 0:
                    entity_graph.run_algorithms()
                    _log.info(
                        "Graph algorithms: %d vertices, %d edges",
                        entity_graph.vertex_count,
                        entity_graph.edge_count,
                    )
            except Exception:
                _log.warning("Graph algorithm execution failed", exc_info=True)

    handler.get_stats = lambda: (event_count, anomaly_count, template_meta, start_time)  # type: ignore[attr-defined]
    return handler
