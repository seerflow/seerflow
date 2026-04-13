"""Pipeline metrics snapshot for the /api/v1/stats endpoint.

Defines an immutable ``PipelineMetrics`` dataclass and a factory that
builds a zero-arg provider callable from a running event handler + detector
ensemble. S-056 defines the wiring; S-075 (CLI) calls the factory in
production after pipeline startup.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


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


MetricsProvider = Callable[[], PipelineMetrics]
