"""Tests for graph-structural correlation evaluator."""

from __future__ import annotations

import pytest

from seerflow.config import ConfigError, _build_detection


class TestGraphStructuralConfigValidation:
    def test_betweenness_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="betweenness_threshold"):
            _build_detection({"graph_structural": {"betweenness_threshold": 0.0}})

    def test_fan_out_sigma_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="fan_out_sigma"):
            _build_detection({"graph_structural": {"fan_out_sigma": 0.0}})

    def test_fan_out_min_floor_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="fan_out_min_floor"):
            _build_detection({"graph_structural": {"fan_out_min_floor": 0}})

    def test_fan_out_history_size_below_3_raises(self) -> None:
        with pytest.raises(ConfigError, match="fan_out_history_size"):
            _build_detection({"graph_structural": {"fan_out_history_size": 2}})


class TestGraphStructuralConfig:
    def test_default_thresholds(self) -> None:
        from seerflow.config import GraphStructuralConfig

        cfg = GraphStructuralConfig()
        assert cfg.betweenness_threshold == 0.3
        assert cfg.fan_out_sigma == 3.0
        assert cfg.fan_out_min_floor == 5
        assert cfg.community_crossing_enabled is True
        assert cfg.fan_out_history_size == 20

    def test_custom_thresholds(self) -> None:
        from seerflow.config import GraphStructuralConfig

        cfg = GraphStructuralConfig(betweenness_threshold=0.5, fan_out_sigma=2.0)
        assert cfg.betweenness_threshold == 0.5

    def test_config_is_frozen(self) -> None:
        import pytest

        from seerflow.config import GraphStructuralConfig

        cfg = GraphStructuralConfig()
        with pytest.raises(AttributeError):
            cfg.betweenness_threshold = 0.9  # type: ignore[misc]


class TestCommunityCrossing:
    def test_crossing_alert_when_different_communities(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("user-1", "host-1", "logged_into", 1_000)
        graph.add_edge("user-2", "host-2", "logged_into", 2_000)
        graph.set_vertex_attr("user-1", "community_id", 0)
        graph.set_vertex_attr("host-1", "community_id", 0)
        graph.set_vertex_attr("user-2", "community_id", 1)
        graph.set_vertex_attr("host-2", "community_id", 1)

        evaluator = GraphStructuralEvaluator(GraphStructuralConfig(), graph)
        alerts = evaluator.check_community_crossing("user-1", "host-2", "logged_into", 3_000)
        assert len(alerts) == 1
        assert "community" in alerts[0].description.lower()
        assert "lateral-movement" in alerts[0].mitre_tactics
        assert alerts[0].alert_type == "correlation"
        assert alerts[0].dedup_key.startswith("graph:community_crossing:")

    def test_no_alert_same_community(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("user-1", "host-1", "logged_into", 1_000)
        graph.set_vertex_attr("user-1", "community_id", 0)
        graph.set_vertex_attr("host-1", "community_id", 0)
        evaluator = GraphStructuralEvaluator(GraphStructuralConfig(), graph)
        alerts = evaluator.check_community_crossing("user-1", "host-1", "logged_into", 2_000)
        assert len(alerts) == 0

    def test_no_alert_when_community_not_assigned(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        evaluator = GraphStructuralEvaluator(GraphStructuralConfig(), graph)
        alerts = evaluator.check_community_crossing("user-1", "host-1", "logged_into", 1_000)
        assert len(alerts) == 0

    def test_no_alert_when_disabled(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("user-1", "host-2", "logged_into", 500)
        graph.set_vertex_attr("user-1", "community_id", 0)
        graph.set_vertex_attr("host-2", "community_id", 1)
        cfg = GraphStructuralConfig(community_crossing_enabled=False)
        evaluator = GraphStructuralEvaluator(cfg, graph)
        alerts = evaluator.check_community_crossing("user-1", "host-2", "logged_into", 1_000)
        assert len(alerts) == 0


class TestBetweennessDetection:
    def test_alert_on_high_betweenness(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("a", "b", "rel", 1_000)
        graph.add_edge("b", "c", "rel", 2_000)
        graph.add_edge("c", "a", "rel", 3_000)
        graph.set_vertex_attr("a", "betweenness", 0.1)
        graph.set_vertex_attr("b", "betweenness", 0.5)
        graph.set_vertex_attr("c", "betweenness", 0.2)

        cfg = GraphStructuralConfig(betweenness_threshold=0.3)
        evaluator = GraphStructuralEvaluator(cfg, graph)
        alerts = evaluator.check_post_algorithms(timestamp_ns=10_000)

        betweenness_alerts = [a for a in alerts if a.rule_name == "graph-high-betweenness"]
        assert len(betweenness_alerts) == 1
        alert = betweenness_alerts[0]
        assert alert.entity_uuid == "b"
        assert alert.alert_type == "correlation"
        assert alert.dedup_key == "graph:betweenness:b"
        assert alert.risk_score == min(1.0, 0.5 * 1.5)
        assert "lateral-movement" in alert.mitre_tactics
        assert alert.severity_id >= 0

    def test_no_alert_below_threshold(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("a", "b", "rel", 1_000)
        graph.set_vertex_attr("a", "betweenness", 0.1)
        graph.set_vertex_attr("b", "betweenness", 0.2)

        cfg = GraphStructuralConfig(betweenness_threshold=0.3)
        evaluator = GraphStructuralEvaluator(cfg, graph)
        alerts = evaluator.check_post_algorithms(timestamp_ns=10_000)

        betweenness_alerts = [a for a in alerts if a.rule_name == "graph-high-betweenness"]
        assert len(betweenness_alerts) == 0

    def test_betweenness_risk_score_capped_at_1(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("a", "b", "rel", 1_000)
        graph.set_vertex_attr("a", "betweenness", 0.9)

        cfg = GraphStructuralConfig(betweenness_threshold=0.3)
        evaluator = GraphStructuralEvaluator(cfg, graph)
        alerts = evaluator.check_post_algorithms(timestamp_ns=10_000)

        betweenness_alerts = [a for a in alerts if a.rule_name == "graph-high-betweenness"]
        assert len(betweenness_alerts) == 1
        assert betweenness_alerts[0].risk_score == 1.0


class TestFanOutDetection:
    def test_alert_on_fan_out_spike(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("a", "b", "rel", 1_000)

        cfg = GraphStructuralConfig(
            betweenness_threshold=99.0,
            fan_out_sigma=2.0,
            fan_out_min_floor=5,
        )
        evaluator = GraphStructuralEvaluator(cfg, graph)

        for fan_out_val in [3, 3, 3, 3, 3]:
            graph.set_vertex_attr("a", "fan_out", fan_out_val)
            graph.set_vertex_attr("b", "fan_out", 0)
            evaluator.check_post_algorithms(timestamp_ns=10_000)

        graph.set_vertex_attr("a", "fan_out", 20)
        graph.set_vertex_attr("b", "fan_out", 0)
        alerts = evaluator.check_post_algorithms(timestamp_ns=20_000)

        fan_out_alerts = [a for a in alerts if a.rule_name == "graph-fan-out-anomaly"]
        assert len(fan_out_alerts) == 1
        alert = fan_out_alerts[0]
        assert alert.entity_uuid == "a"
        assert alert.alert_type == "correlation"
        assert alert.dedup_key == "graph:fan_out:a"
        assert "lateral-movement" in alert.mitre_tactics

    def test_no_alert_below_floor(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("a", "b", "rel", 1_000)

        cfg = GraphStructuralConfig(
            betweenness_threshold=99.0,
            fan_out_sigma=2.0,
            fan_out_min_floor=5,
        )
        evaluator = GraphStructuralEvaluator(cfg, graph)

        for fan_out_val in [1, 1, 1]:
            graph.set_vertex_attr("a", "fan_out", fan_out_val)
            graph.set_vertex_attr("b", "fan_out", 0)
            evaluator.check_post_algorithms(timestamp_ns=10_000)

        graph.set_vertex_attr("a", "fan_out", 3)
        graph.set_vertex_attr("b", "fan_out", 0)
        alerts = evaluator.check_post_algorithms(timestamp_ns=20_000)

        fan_out_alerts = [a for a in alerts if a.rule_name == "graph-fan-out-anomaly"]
        assert len(fan_out_alerts) == 0

    def test_no_alert_insufficient_history(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("a", "b", "rel", 1_000)
        graph.set_vertex_attr("a", "fan_out", 100)
        graph.set_vertex_attr("b", "fan_out", 0)

        cfg = GraphStructuralConfig(betweenness_threshold=99.0)
        evaluator = GraphStructuralEvaluator(cfg, graph)

        alerts1 = evaluator.check_post_algorithms(timestamp_ns=10_000)
        fan_out_alerts1 = [a for a in alerts1 if a.rule_name == "graph-fan-out-anomaly"]
        assert len(fan_out_alerts1) == 0

        alerts2 = evaluator.check_post_algorithms(timestamp_ns=11_000)
        fan_out_alerts2 = [a for a in alerts2 if a.rule_name == "graph-fan-out-anomaly"]
        assert len(fan_out_alerts2) == 0

    def test_fan_out_history_capped(self) -> None:
        from seerflow.config import GraphStructuralConfig
        from seerflow.correlation.graph_structural import GraphStructuralEvaluator
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("a", "b", "rel", 1_000)

        cfg = GraphStructuralConfig(
            betweenness_threshold=99.0,
            fan_out_history_size=5,
        )
        evaluator = GraphStructuralEvaluator(cfg, graph)

        for i in range(10):
            graph.set_vertex_attr("a", "fan_out", i)
            graph.set_vertex_attr("b", "fan_out", 0)
            evaluator.check_post_algorithms(timestamp_ns=i * 1_000)

        assert len(evaluator._fan_out_history["a"]) <= 5


class TestAllEntityIds:
    def test_returns_all_vertex_keys(self) -> None:
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        graph.add_edge("a", "b", "rel", 1_000)
        graph.add_edge("c", "d", "rel", 2_000)
        ids = graph.all_entity_ids()
        assert set(ids) == {"a", "b", "c", "d"}

    def test_empty_graph(self) -> None:
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        assert graph.all_entity_ids() == []
