"""Event handler factory for the Seerflow pipeline."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import msgspec.structs

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from seerflow.alerting.dispatcher import AlertDispatcher
    from seerflow.alerting.sinks.otlp import OtlpSink
    from seerflow.alerting.sinks.pagerduty import PagerDutySink
    from seerflow.config import AlertingConfig
    from seerflow.correlation.engine import CorrelationEngine
    from seerflow.correlation.graph_structural import GraphStructuralEvaluator
    from seerflow.correlation.holders import EngineHolder
    from seerflow.correlation.kill_chain import KillChainTracker
    from seerflow.correlation.risk import RiskRegister
    from seerflow.correlation.watermark import Watermark
    from seerflow.correlation.window import EntityWindowBuffer
    from seerflow.detection.attack_mapping import AttackMapper
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.graph.entity_graph import EntityGraph
    from seerflow.receivers.base import RawEvent
    from seerflow.sigma.engine import SigmaEngine
    from seerflow.storage.sqlite import SqliteBackend

_log = logging.getLogger("seerflow")


@dataclass(frozen=True, slots=True)
class EntityDispatch:
    """Named dispatch record for entity resolution."""

    type_name: str
    raw_vals: tuple[str, ...]
    ips: tuple[str, ...]
    users: tuple[str, ...]
    hosts: tuple[str, ...]
    kwargs: Mapping[str, tuple[str, ...]]


def _dedup_window_ns(rule_name: str, alerting_config: AlertingConfig) -> int:
    """Return the dedup window in nanoseconds for a given rule name.

    Checks ``alerting_config.dedup_window_overrides`` for a per-rule override;
    falls back to the global ``dedup_window_seconds``.
    """
    for override_name, seconds in alerting_config.dedup_window_overrides:
        if rule_name == override_name:
            return seconds * 1_000_000_000
    return alerting_config.dedup_window_seconds * 1_000_000_000


def make_handler(
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
    alerting_config: AlertingConfig | None = None,
    alert_dispatcher: AlertDispatcher | None = None,
    pagerduty_sink: PagerDutySink | None = None,
    otlp_sink: OtlpSink | None = None,
    attack_mapper: AttackMapper | None = None,
    graph_structural: GraphStructuralEvaluator | None = None,
    kill_chain_tracker: KillChainTracker | None = None,
) -> Callable[[RawEvent], Awaitable[None]]:
    """Create an event handler that runs detection and persists events."""
    from seerflow.config import AlertingConfig as _AlertingConfig
    from seerflow.graph.edges import infer_edges
    from seerflow.models.alert import Alert, create_ml_alerts
    from seerflow.models.entity import resolve_entities, sanitize_for_log
    from seerflow.parsing import EventNormalizer
    from seerflow.storage.sqlite import TemplateInfo

    _alerting = alerting_config if alerting_config is not None else _AlertingConfig()
    normalizer = EventNormalizer()
    event_count = 0
    anomaly_count = 0
    template_meta: dict[int, TemplateInfo] = {}
    start_time = time.time()
    last_save_ns = time.time_ns()
    risk_alerted: set[str] = set()  # entities that already fired a risk alert

    async def _feed_kill_chain(alert: Alert) -> None:
        """Feed an alert to the kill-chain tracker and write any resulting alerts."""
        if kill_chain_tracker is None:
            return
        for kc in kill_chain_tracker.record_alert(alert):
            try:
                is_new = await storage.write_alert(
                    kc,
                    dedup_window_ns=_dedup_window_ns(kc.rule_name, _alerting),
                )
                if is_new:
                    if alert_dispatcher is not None:
                        alert_dispatcher.enqueue(kc)
                    if pagerduty_sink is not None:
                        pagerduty_sink.enqueue_trigger(kc)
                    if otlp_sink is not None:
                        otlp_sink.enqueue(kc)
            except Exception:
                _log.warning("Kill-chain alert write failed", exc_info=True)

    async def handler(event: RawEvent) -> None:
        nonlocal event_count, anomaly_count, last_save_ns
        seerflow_event = normalizer.normalize(event)

        # Resolve entities to deterministic UUID5 strings.
        # Resolve each type separately to build both entity_refs (flat tuple
        # for correlation/risk) and typed_for_edges (typed pairs for edge
        # inference) in a single pass.
        typed_for_edges: list[tuple[str, str]] = []
        entity_refs_list: list[str] = []
        _ips = seerflow_event.related_ips
        _users = seerflow_event.related_users
        _hosts = seerflow_event.related_hosts
        _domains = seerflow_event.related_domains
        _files = seerflow_event.related_files
        _procs = seerflow_event.related_processes
        for d in (
            EntityDispatch("ip", _ips, _ips, (), (), {}),
            EntityDispatch("user", _users, (), _users, (), {}),
            EntityDispatch("host", _hosts, (), (), _hosts, {}),
            EntityDispatch(
                "domain",
                _domains,
                (),
                (),
                (),
                {"domains": _domains},
            ),
            EntityDispatch(
                "file",
                _files,
                (),
                (),
                (),
                {"files": _files},
            ),
            EntityDispatch(
                "process",
                _procs,
                (),
                (),
                (),
                {"processes": _procs},
            ),
        ):
            if d.raw_vals:
                for _uid in resolve_entities(d.ips, d.users, d.hosts, **d.kwargs):
                    typed_for_edges.append((d.type_name, _uid))
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
                        is_new = await storage.write_alert(
                            corr_alert,
                            dedup_window_ns=_dedup_window_ns(corr_alert.rule_name, _alerting),
                        )
                        if is_new:
                            if alert_dispatcher is not None:
                                alert_dispatcher.enqueue(corr_alert)
                            if pagerduty_sink is not None:
                                pagerduty_sink.enqueue_trigger(corr_alert)
                            if otlp_sink is not None:
                                otlp_sink.enqueue(corr_alert)
                        await _feed_kill_chain(corr_alert)
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

        # Dedup typed_for_edges to avoid redundant edge inference
        typed_for_edges = list(dict.fromkeys(typed_for_edges))

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

            # Check community-crossing after all edges are added
            if graph_structural is not None:
                for edge in edges:
                    cc_alerts = graph_structural.check_community_crossing(
                        edge.source_id,
                        edge.target_id,
                        edge.rel_type,
                        seerflow_event.timestamp_ns,
                    )
                    for cc_alert in cc_alerts:
                        try:
                            is_new = await storage.write_alert(
                                cc_alert,
                                dedup_window_ns=_dedup_window_ns(cc_alert.rule_name, _alerting),
                            )
                            if is_new:
                                if alert_dispatcher is not None:
                                    alert_dispatcher.enqueue(cc_alert)
                                if pagerduty_sink is not None:
                                    pagerduty_sink.enqueue_trigger(cc_alert)
                                if otlp_sink is not None:
                                    otlp_sink.enqueue(cc_alert)
                            await _feed_kill_chain(cc_alert)
                        except Exception:
                            _log.warning(
                                "Graph structural alert write failed",
                                exc_info=True,
                            )

        # Track template metadata
        if seerflow_event.template_id != -1:
            if seerflow_event.template_id not in template_meta:
                _log.info(
                    "New template discovered: [%d] %s",
                    seerflow_event.template_id,
                    seerflow_event.template_str[:120].replace("\x00", ""),
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
                seerflow_event.template_str[:120].replace("\x00", ""),
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
            _mitre_tactics: tuple[str, ...] = ()
            _mitre_techniques: tuple[str, ...] = ()
            if attack_mapper is not None and seerflow_event.template_str:
                _mitre_tactics, _mitre_techniques = attack_mapper.lookup(
                    seerflow_event.template_str
                )
            alerts = create_ml_alerts(
                seerflow_event,
                result,
                typed_for_edges,
                mitre_tactics=_mitre_tactics,
                mitre_techniques=_mitre_techniques,
            )
            for alert in alerts:
                try:
                    is_new = await storage.write_alert(
                        alert,
                        dedup_window_ns=_dedup_window_ns(alert.rule_name, _alerting),
                    )
                    if is_new:
                        if alert_dispatcher is not None:
                            alert_dispatcher.enqueue(alert)
                        if pagerduty_sink is not None:
                            pagerduty_sink.enqueue_trigger(alert)
                        if otlp_sink is not None:
                            otlp_sink.enqueue(alert)
                    await _feed_kill_chain(alert)
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
                        mitre_tactics=_mitre_tactics,
                        mitre_techniques=_mitre_techniques,
                    )
                    risk_register.add_risk(entity_uuid, risk_entry)

        # Sigma rule evaluation
        sigma_engine = sigma_holder.engine if sigma_holder is not None else None
        if sigma_engine is not None:
            try:
                sigma_alerts = sigma_engine.evaluate(seerflow_event)
                for sigma_alert in sigma_alerts:
                    try:
                        is_new = await storage.write_alert(
                            sigma_alert,
                            dedup_window_ns=_dedup_window_ns(sigma_alert.rule_name, _alerting),
                        )
                        if is_new:
                            if alert_dispatcher is not None:
                                alert_dispatcher.enqueue(sigma_alert)
                            if pagerduty_sink is not None:
                                pagerduty_sink.enqueue_trigger(sigma_alert)
                            if otlp_sink is not None:
                                otlp_sink.enqueue(sigma_alert)
                        await _feed_kill_chain(sigma_alert)
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
                        is_new = await storage.write_alert(
                            risk_alert,
                            dedup_window_ns=_dedup_window_ns(risk_alert.rule_name, _alerting),
                        )
                        if is_new:
                            if alert_dispatcher is not None:
                                alert_dispatcher.enqueue(risk_alert)
                            if pagerduty_sink is not None:
                                pagerduty_sink.enqueue_trigger(risk_alert)
                            if otlp_sink is not None:
                                otlp_sink.enqueue(risk_alert)
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
        _algo_ran = False
        if entity_graph is not None and entity_graph.vertex_count > 0:
            try:
                if event_count % graph_algo_interval == 0:
                    entity_graph.run_algorithms()
                    _algo_ran = True
                    _log.info(
                        "Graph algorithms: %d vertices, %d edges",
                        entity_graph.vertex_count,
                        entity_graph.edge_count,
                    )
            except Exception:
                _log.warning("Graph algorithm execution failed", exc_info=True)

            # Evaluate post-algorithm graph-structural anomalies (only if algorithms ran)
            if graph_structural is not None and _algo_ran:
                post_alerts = graph_structural.check_post_algorithms(
                    timestamp_ns=seerflow_event.timestamp_ns,
                )
                for pa in post_alerts:
                    try:
                        is_new = await storage.write_alert(
                            pa,
                            dedup_window_ns=_dedup_window_ns(pa.rule_name, _alerting),
                        )
                        if is_new:
                            if alert_dispatcher is not None:
                                alert_dispatcher.enqueue(pa)
                            if pagerduty_sink is not None:
                                pagerduty_sink.enqueue_trigger(pa)
                            if otlp_sink is not None:
                                otlp_sink.enqueue(pa)
                        await _feed_kill_chain(pa)
                    except Exception:
                        _log.warning(
                            "Graph structural alert write failed",
                            exc_info=True,
                        )

    handler.get_stats = lambda: (event_count, anomaly_count, template_meta, start_time)  # type: ignore[attr-defined]
    return handler
