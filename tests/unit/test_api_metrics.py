"""Tests for api.metrics — PipelineMetrics + provider factory."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from seerflow.api.metrics import PipelineMetrics, build_pipeline_metrics_provider


class TestPipelineMetrics:
    def test_is_frozen(self) -> None:
        m = PipelineMetrics(
            started_monotonic=100.0,
            total_events_processed=500,
            active_sources=2,
            model_count=8,
        )
        with pytest.raises(FrozenInstanceError):
            m.total_events_processed = 999  # type: ignore[misc]

    def test_field_values(self) -> None:
        m = PipelineMetrics(
            started_monotonic=100.0,
            total_events_processed=500,
            active_sources=2,
            model_count=8,
        )
        assert m.started_monotonic == 100.0
        assert m.total_events_processed == 500
        assert m.active_sources == 2
        assert m.model_count == 8


class TestBuildProvider:
    def test_provider_reads_handler_stats(self) -> None:
        handler = type("H", (), {"get_stats": lambda self: (1500, 42, {}, 0.0)})()
        ensemble = type("E", (), {"get_stats": lambda self: {"source_count": 3}})()
        provider = build_pipeline_metrics_provider(
            handler=handler,
            ensemble=ensemble,
            started_monotonic=100.0,
        )
        m = provider()
        assert m.started_monotonic == 100.0
        assert m.total_events_processed == 1500
        assert m.active_sources == 3
        assert m.model_count == 12  # 3 sources * 4 detectors/source

    def test_provider_with_missing_get_stats_returns_zero(self) -> None:
        handler = object()
        ensemble = type("E", (), {"get_stats": lambda self: {"source_count": 0}})()
        provider = build_pipeline_metrics_provider(
            handler=handler,
            ensemble=ensemble,
            started_monotonic=50.0,
        )
        m = provider()
        assert m.total_events_processed == 0
        assert m.active_sources == 0
        assert m.model_count == 0

    def test_provider_with_none_ensemble(self) -> None:
        handler = type("H", (), {"get_stats": lambda self: (99, 0, {}, 0.0)})()
        provider = build_pipeline_metrics_provider(
            handler=handler,
            ensemble=None,
            started_monotonic=0.0,
        )
        m = provider()
        assert m.total_events_processed == 99
        assert m.active_sources == 0
        assert m.model_count == 0

    def test_provider_prefers_total_model_count_when_present(self) -> None:
        """S-075: when ``ensemble.get_stats()`` exposes ``total_model_count``,
        the provider must use that value instead of the
        ``source_count * _DETECTORS_PER_SOURCE`` multiplier.

        Heterogeneous ensembles (e.g. UEBA-disabled, Markov-off) report a
        non-uniform per-source detector count; the multiplier is wrong for
        those, while the ensemble-derived total is authoritative.
        """
        handler = type("H", (), {"get_stats": lambda self: (10, 0, {}, 0.0)})()
        ensemble = type(
            "E",
            (),
            {
                "get_stats": lambda self: {
                    "source_count": 3,
                    "total_model_count": 7,  # heterogeneous — 3 * 4 = 12 would be wrong
                }
            },
        )()
        provider = build_pipeline_metrics_provider(
            handler=handler,
            ensemble=ensemble,
            started_monotonic=0.0,
        )
        m = provider()
        assert m.active_sources == 3
        assert m.model_count == 7  # taken from total_model_count, not 3*4=12

    def test_provider_falls_back_to_multiplier_when_total_missing(self) -> None:
        """Backwards-compat: ensembles / mocks that do not surface
        ``total_model_count`` keep the historical ``source_count * 4``
        behaviour so existing tests and partial mocks remain green.
        """
        handler = type("H", (), {"get_stats": lambda self: (10, 0, {}, 0.0)})()
        ensemble = type("E", (), {"get_stats": lambda self: {"source_count": 5}})()
        provider = build_pipeline_metrics_provider(
            handler=handler,
            ensemble=ensemble,
            started_monotonic=0.0,
        )
        m = provider()
        assert m.active_sources == 5
        assert m.model_count == 20  # fallback: 5 * _DETECTORS_PER_SOURCE (=4)


def test_pipeline_metrics_includes_ioc_matcher_field() -> None:
    from seerflow.api.metrics import PipelineMetrics
    from seerflow.threat_intel.matcher import IoCMatcherMetrics

    m = PipelineMetrics(
        started_monotonic=0.0,
        total_events_processed=0,
        active_sources=0,
        model_count=0,
        ioc_matcher=IoCMatcherMetrics(),
    )
    assert m.ioc_matcher is not None
    assert m.ioc_matcher.rebuild_count == 0
