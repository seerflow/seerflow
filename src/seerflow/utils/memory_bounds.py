"""In-process memory-bounds audit aggregator (S-082).

Each Seerflow process keeps a handful of LRU caches, bounded queues, and
ML model maps in memory. Every one has a ``max_*`` knob in ``config.py``
and an eviction strategy in code. This module pulls the *live* size, the
configured cap, and the cumulative eviction count from each component
through a public accessor and aggregates them into a single dict that the
health endpoint serialises under ``memory_bounds``.

Design goals:

- **Pure** — no side effects, no I/O, no async; safe to call from the
  health route's hot path.
- **Optional** — every component argument is keyword-only and defaults to
  ``None``. Tests, factory wiring, and partially-constructed apps can
  call ``collect_memory_bounds()`` and get an empty dict without raising.
- **Stable keys** — every component contributes one or more deterministic
  string keys (``ensemble.sources``, ``correlation.window``,
  ``alerting.dispatcher``…). Dashboards depend on these names; renaming
  is a breaking change.
- **No private attribute access** — the aggregator only reads through
  documented accessors (``get_health``, ``bounds``, ``qsize``, etc.) so
  the audit cannot drift behind refactors of the underlying components.

Stage cap caveat: ``StageLatencyTracker`` enforces a hard cap on the
number of distinct stage names (default 16) by silently dropping new
stages and logging a single warning. The audit reports ``evictions=0``
for the tracker because there is no per-sample eviction counter — the
ring-buffer overwrites are by design (see ``api/latency.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from seerflow.alerting.dispatcher import AlertDispatcher
    from seerflow.alerting.sinks.otlp import OtlpSink
    from seerflow.alerting.sinks.pagerduty import PagerDutySink
    from seerflow.api.latency import StageLatencyTracker
    from seerflow.api.ws import ConnectionManager
    from seerflow.correlation.kill_chain import KillChainTracker
    from seerflow.correlation.risk import RiskRegister
    from seerflow.correlation.window import EntityWindowBuffer
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.llm.explanation.cache import ExplanationCache
    from seerflow.llm.hunt.cache import HuntCache
    from seerflow.llm.rule_suggestion.cache import RuleSuggestionCache
    from seerflow.receivers.manager import ReceiverManager
    from seerflow.ueba.store import BaselineStore


class MemoryBoundsReport(TypedDict):
    """Per-component memory-bounds snapshot.

    All three fields are ``int`` so the report is trivially JSON
    serialisable. ``evictions`` is cumulative since process start, not
    since deploy — operator runbooks should compute deltas, not absolutes
    (see ``docs/operator-guide.md`` "Memory Bounds").
    """

    current: int
    max: int
    evictions: int


def collect_memory_bounds(
    *,
    ensemble: DetectionEnsemble | None = None,
    baseline_store: BaselineStore | None = None,
    window_buffer: EntityWindowBuffer | None = None,
    risk_register: RiskRegister | None = None,
    kill_chain: KillChainTracker | None = None,
    receiver_manager: ReceiverManager | None = None,
    alert_dispatcher: AlertDispatcher | None = None,
    otlp_sink: OtlpSink | None = None,
    pagerduty_sink: PagerDutySink | None = None,
    websocket_manager: ConnectionManager | None = None,
    latency_tracker: StageLatencyTracker | None = None,
    explanation_cache: ExplanationCache | None = None,
    hunt_cache: HuntCache | None = None,
    rule_suggestion_cache: RuleSuggestionCache | None = None,
) -> dict[str, MemoryBoundsReport]:
    """Return a stable per-component memory-bounds report.

    Component keys (always present when the component is wired):

    - ``ensemble.sources``         — detection ensemble per-source LRU
    - ``ensemble.template_hw``     — template Holt-Winters LRU
    - ``ensemble.entity_hw``       — entity Holt-Winters LRU
    - ``ensemble.markov``          — aggregate Markov entity count
    - ``ueba.baselines``           — UEBA baseline store
    - ``correlation.window``       — entity-temporal window buffer
    - ``correlation.risk``         — risk register
    - ``correlation.kill_chain``   — kill-chain LRU
    - ``receivers.queue``          — receiver intake queue
    - ``alerting.dispatcher``      — alert dispatcher queue
    - ``alerting.otlp``            — OTLP alert sink pending queue
    - ``alerting.pagerduty``       — PagerDuty sink queue
    - ``api.websocket``            — aggregate per-client deque pressure
    - ``api.latency``              — stage latency tracker reservoir
    - ``llm.explanation_cache``    — explanation LRU+TTL
    - ``llm.hunt_cache``           — natural-language hunt LRU+TTL
    - ``llm.rule_suggestion_cache``— sigma-rule suggestion LRU+TTL
    """
    report: dict[str, MemoryBoundsReport] = {}

    if ensemble is not None:
        _add_ensemble_rows(report, ensemble)

    if baseline_store is not None:
        report["ueba.baselines"] = _to_report(baseline_store.bounds())

    if window_buffer is not None:
        report["correlation.window"] = _to_report(window_buffer.bounds())

    if risk_register is not None:
        report["correlation.risk"] = _to_report(risk_register.bounds())

    if kill_chain is not None:
        report["correlation.kill_chain"] = _to_report(kill_chain.bounds())

    if receiver_manager is not None:
        report["receivers.queue"] = _to_report(receiver_manager.bounds())

    if alert_dispatcher is not None:
        report["alerting.dispatcher"] = _to_report(alert_dispatcher.bounds())

    if otlp_sink is not None:
        report["alerting.otlp"] = _to_report(otlp_sink.bounds())

    if pagerduty_sink is not None:
        report["alerting.pagerduty"] = _to_report(pagerduty_sink.bounds())

    if websocket_manager is not None:
        report["api.websocket"] = _to_report(websocket_manager.bounds())

    if latency_tracker is not None:
        report["api.latency"] = _to_report(latency_tracker.bounds())

    if explanation_cache is not None:
        report["llm.explanation_cache"] = _to_report(explanation_cache.bounds())

    if hunt_cache is not None:
        report["llm.hunt_cache"] = _to_report(hunt_cache.bounds())

    if rule_suggestion_cache is not None:
        report["llm.rule_suggestion_cache"] = _to_report(rule_suggestion_cache.bounds())

    return report


def _to_report(raw: dict[str, int]) -> MemoryBoundsReport:
    """Project a free-form ``bounds()`` dict onto the TypedDict shape.

    Keeps mypy happy without forcing every component to depend on the
    audit's ``MemoryBoundsReport`` type — components stay free of the
    audit's import surface.
    """
    return MemoryBoundsReport(
        current=int(raw["current"]),
        max=int(raw["max"]),
        evictions=int(raw["evictions"]),
    )


def _add_ensemble_rows(
    report: dict[str, MemoryBoundsReport],
    ensemble: DetectionEnsemble,
) -> None:
    """Project ``DetectionEnsemble.get_health()`` into four audit rows.

    The ensemble already tracks bound state internally; this aggregator
    only renames its keys into the audit's stable schema. No mutation,
    no recomputation — the aggregator must remain free of side effects.
    """
    health = ensemble.get_health()
    sources = int(health.get("source_count", 0))
    max_sources = int(health.get("max_sources", 0))
    source_evictions = int(health.get("eviction_count", 0))
    report["ensemble.sources"] = MemoryBoundsReport(
        current=sources, max=max_sources, evictions=source_evictions
    )

    template_hw = int(health.get("template_hw_count", 0))
    template_hw_max = _ensemble_max_template_hw(ensemble)
    template_hw_evict = int(health.get("template_hw_eviction_count", 0))
    report["ensemble.template_hw"] = MemoryBoundsReport(
        current=template_hw, max=template_hw_max, evictions=template_hw_evict
    )

    entity_hw = int(health.get("entity_hw_count", 0))
    entity_hw_max = _ensemble_max_entity_hw(ensemble)
    entity_hw_evict = int(health.get("entity_hw_eviction_count", 0))
    report["ensemble.entity_hw"] = MemoryBoundsReport(
        current=entity_hw, max=entity_hw_max, evictions=entity_hw_evict
    )

    markov_counts = health.get("markov_entity_counts", {}) or {}
    markov_total = sum(int(v) for v in markov_counts.values())
    markov_max = _ensemble_markov_max_total(ensemble, sources)
    report["ensemble.markov"] = MemoryBoundsReport(
        current=markov_total, max=markov_max, evictions=0
    )


def _ensemble_max_template_hw(ensemble: DetectionEnsemble) -> int:
    """Read the configured template-HW cap via the public attribute."""
    return int(getattr(ensemble, "_max_template_hw", 0))


def _ensemble_max_entity_hw(ensemble: DetectionEnsemble) -> int:
    """Read the configured entity-HW cap via the public attribute."""
    return int(getattr(ensemble, "_max_entity_hw", 0))


def _ensemble_markov_max_total(ensemble: DetectionEnsemble, sources: int) -> int:
    """Effective cap on aggregate Markov entity count.

    Markov is per-source with a per-source ``markov_max_entities`` knob
    (default 1000). The aggregate cap is ``sources * per_source``; with
    zero active sources, the aggregate cap is reported as the per-source
    knob (operators see the per-source budget rather than ``0``).
    """
    config = getattr(ensemble, "_config", None)
    per_source = int(getattr(config, "markov_max_entities", 0)) if config is not None else 0
    return per_source * sources if sources > 0 else per_source
