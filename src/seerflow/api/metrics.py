"""Pipeline metrics snapshot for the /api/v1/stats endpoint.

Defines an immutable ``PipelineMetrics`` dataclass and a factory that
builds a zero-arg provider callable from a running event handler + detector
ensemble. S-056 defines the wiring; S-075 (CLI) calls the factory in
production after pipeline startup.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from seerflow.threat_intel.metrics import (
        TAXIIMetricsAggregate,
        TAXIIMetricsRegistry,
    )


@dataclass(frozen=True, slots=True)
class PipelineMetrics:
    """Immutable snapshot of running pipeline stats.

    Each stats request builds a fresh instance — there is no long-lived
    metrics object. Uses ``time.monotonic()`` (not wall clock) for uptime
    so it cannot be skewed by NTP adjustments.
    """

    started_monotonic: float
    total_events_processed: int
    active_sources: int
    model_count: int
    taxii: TAXIIMetricsAggregate | None = None


MetricsProvider = Callable[[], PipelineMetrics]


_DETECTORS_PER_SOURCE = 4  # HST + HW + CUSUM + Markov (v1 ensemble composition)


def build_pipeline_metrics_provider(
    handler: Any,
    ensemble: Any,
    started_monotonic: float,
    taxii_registry: TAXIIMetricsRegistry | None = None,
) -> MetricsProvider:
    """Return a zero-arg callable that yields a fresh PipelineMetrics.

    ``handler`` is expected to have a ``get_stats()`` method returning
    ``(event_count, anomaly_count, template_meta, start_time)`` — matches
    the shape attached in ``pipeline.handler.create_handler``. If the
    attribute is missing, the provider returns zero event count (used by
    tests or partially constructed pipelines).

    ``ensemble`` is expected to have a ``get_stats()`` returning a dict
    with a ``source_count`` key. ``None`` is allowed (returns zero).

    ``taxii_registry`` is the running ``TAXIIMetricsRegistry`` owned by
    the ``TAXIIFeedManager``. ``None`` (or a registry with no feeds) leaves
    ``PipelineMetrics.taxii = None`` so the stats route can omit the field.
    """

    def _provider() -> PipelineMetrics:
        event_count = 0
        get_stats = getattr(handler, "get_stats", None)
        if get_stats is not None:
            events, _anomalies, _templates, _t0 = get_stats()
            event_count = int(events)
        active = 0
        if ensemble is not None:
            active = int(ensemble.get_stats().get("source_count", 0))
        taxii: TAXIIMetricsAggregate | None = None
        if taxii_registry is not None:
            taxii = taxii_registry.aggregate()
        return PipelineMetrics(
            started_monotonic=started_monotonic,
            total_events_processed=event_count,
            active_sources=active,
            model_count=active * _DETECTORS_PER_SOURCE,
            taxii=taxii,
        )

    return _provider
