"""Graph-structural correlation evaluator.

Detects anomalous graph patterns — community crossings, betweenness
centrality spikes, and fan-out bursts — on the entity graph.
"""

from __future__ import annotations

import statistics
import uuid
from typing import TYPE_CHECKING

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

if TYPE_CHECKING:
    from seerflow.config import GraphStructuralConfig
    from seerflow.graph.entity_graph import EntityGraph

_LATERAL_TACTICS = ("lateral-movement",)
_LATERAL_TECHNIQUES = ("T1021",)

_MIN_FAN_OUT_HISTORY = 3


class GraphStructuralEvaluator:
    """Evaluate graph-structural anomalies on the entity graph.

    Supports community-crossing detection, betweenness-centrality spikes,
    and fan-out burst detection.
    """

    __slots__ = ("_config", "_fan_out_history", "_graph")

    def __init__(self, config: GraphStructuralConfig, graph: EntityGraph) -> None:
        self._config = config
        self._graph = graph
        self._fan_out_history: dict[str, list[int]] = {}

    def check_community_crossing(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        timestamp_ns: int,
    ) -> list[Alert]:
        """Return an alert if *source_id* and *target_id* are in different communities.

        Returns an empty list when:
        - community-crossing detection is disabled in config
        - either vertex has no ``community_id`` attribute
        - both vertices share the same community
        """
        if not self._config.community_crossing_enabled:
            return []

        src_comm = self._graph.get_vertex_attr(source_id, "community_id")
        tgt_comm = self._graph.get_vertex_attr(target_id, "community_id")

        if src_comm is None or tgt_comm is None or src_comm == tgt_comm:
            return []

        alert_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"graph:cc:{source_id}:{target_id}:{timestamp_ns}",
            )
        )

        return [
            Alert(
                alert_id=alert_id,
                alert_type="correlation",
                timestamp_ns=timestamp_ns,
                severity_id=SeverityLevel.WARNING,
                rule_name="graph-community-crossing",
                description=(
                    f"Community-crossing edge: {source_id[:8]}...→{target_id[:8]}... "
                    f"({rel_type}), communities {src_comm}→{tgt_comm}"
                ),
                entity_uuid=source_id,
                entity_value=source_id[:16],
                entity_type="host",
                contributing_events=(),
                mitre_tactics=_LATERAL_TACTICS,
                mitre_techniques=_LATERAL_TECHNIQUES,
                risk_score=0.6,
                dedup_key=f"graph:community_crossing:{source_id}",
            )
        ]

    def check_post_algorithms(self, *, timestamp_ns: int) -> list[Alert]:
        """Scan all vertices for betweenness and fan-out anomalies.

        Should be called after ``EntityGraph.run_algorithms()`` has refreshed
        vertex attributes.  Returns alerts for:

        - **High betweenness:** entities whose betweenness centrality exceeds
          ``config.betweenness_threshold``.
        - **Fan-out anomaly:** entities whose current fan-out exceeds the
          rolling mean + N*sigma (where N = ``config.fan_out_sigma``) and is
          at least ``config.fan_out_min_floor``.
        """
        alerts: list[Alert] = []
        entity_ids = self._graph.all_entity_ids()

        for entity_id in entity_ids:
            alerts.extend(self._check_betweenness(entity_id, timestamp_ns))
            alerts.extend(self._check_fan_out(entity_id, timestamp_ns))

        return alerts

    def _check_betweenness(
        self,
        entity_id: str,
        timestamp_ns: int,
    ) -> list[Alert]:
        """Create an alert if the entity's betweenness exceeds the threshold."""
        betweenness_raw = self._graph.get_vertex_attr(entity_id, "betweenness")
        if not isinstance(betweenness_raw, (int, float)):
            return []

        betweenness_val = float(betweenness_raw)
        if betweenness_val <= self._config.betweenness_threshold:
            return []

        alert_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"graph:betweenness:{entity_id}:{timestamp_ns}",
            )
        )
        return [
            Alert(
                alert_id=alert_id,
                alert_type="correlation",
                timestamp_ns=timestamp_ns,
                severity_id=SeverityLevel.WARNING,
                rule_name="graph-high-betweenness",
                description=(
                    f"High betweenness centrality: {entity_id[:8]}... "
                    f"betweenness={betweenness_val:.3f} "
                    f"(threshold={self._config.betweenness_threshold:.3f})"
                ),
                entity_uuid=entity_id,
                entity_value=entity_id[:16],
                entity_type="host",
                contributing_events=(),
                mitre_tactics=_LATERAL_TACTICS,
                mitre_techniques=_LATERAL_TECHNIQUES,
                risk_score=min(1.0, betweenness_val * 1.5),
                dedup_key=f"graph:betweenness:{entity_id}",
            )
        ]

    def _check_fan_out(
        self,
        entity_id: str,
        timestamp_ns: int,
    ) -> list[Alert]:
        """Create an alert if the entity's fan-out is anomalously high."""
        fan_out_raw = self._graph.get_vertex_attr(entity_id, "fan_out")
        if not isinstance(fan_out_raw, (int, float)):
            return []

        current_fan_out = int(fan_out_raw)
        history = self._fan_out_history.get(entity_id, [])

        if len(history) < _MIN_FAN_OUT_HISTORY:
            self._fan_out_history.setdefault(entity_id, []).append(current_fan_out)
            return []

        mean = statistics.mean(history)
        stddev = statistics.stdev(history) if len(history) >= 2 else 0.0
        threshold = mean + self._config.fan_out_sigma * stddev

        # Append current value and cap history size.
        history.append(current_fan_out)
        if len(history) > self._config.fan_out_history_size:
            del history[: len(history) - self._config.fan_out_history_size]

        if current_fan_out <= threshold:
            return []
        if current_fan_out < self._config.fan_out_min_floor:
            return []

        alert_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"graph:fan_out:{entity_id}:{timestamp_ns}",
            )
        )
        return [
            Alert(
                alert_id=alert_id,
                alert_type="correlation",
                timestamp_ns=timestamp_ns,
                severity_id=SeverityLevel.WARNING,
                rule_name="graph-fan-out-anomaly",
                description=(
                    f"Fan-out anomaly: {entity_id[:8]}... "
                    f"fan_out={current_fan_out} "
                    f"(mean={mean:.1f}, threshold={threshold:.1f})"
                ),
                entity_uuid=entity_id,
                entity_value=entity_id[:16],
                entity_type="host",
                contributing_events=(),
                mitre_tactics=_LATERAL_TACTICS,
                mitre_techniques=_LATERAL_TECHNIQUES,
                risk_score=min(1.0, current_fan_out / max(threshold, 1.0)),
                dedup_key=f"graph:fan_out:{entity_id}",
            )
        ]
