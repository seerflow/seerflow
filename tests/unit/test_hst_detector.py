"""Tests for HSTDetector — Half-Space Trees anomaly detector."""

from __future__ import annotations

import uuid

from seerflow.models import SeerflowEvent, SeverityLevel


def _make_event(**overrides: object) -> SeerflowEvent:
    """Helper to create a minimal valid SeerflowEvent."""
    defaults: dict[str, object] = {
        "event_id": uuid.uuid4(),
        "timestamp_ns": 1_700_000_000_000_000_000,
        "observed_ns": 1_700_000_000_000_000_000,
        "message": "test message",
        "template_id": 1,
        "severity_id": SeverityLevel.INFORMATIONAL,
    }
    defaults.update(overrides)
    return SeerflowEvent(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Feature extraction tests
# ---------------------------------------------------------------------------


class TestFeatureExtraction:
    def test_basic_features_present(self) -> None:
        from seerflow.detection.hst import _extract_features

        event = _make_event(
            template_id=42,
            entity_refs=("ent1", "ent2"),
            severity_id=SeverityLevel.ERROR,
            template_params=("p1", "p2", "p3"),
            message="hello world",
        )
        features = _extract_features(event)

        assert features["tid_42"] == 1.0
        assert features["entity_count"] == 2.0
        assert features["severity"] == float(SeverityLevel.ERROR.value)
        assert features["param_count"] == 3.0
        assert features["msg_length"] == float(len("hello world"))

    def test_default_event_features(self) -> None:
        from seerflow.detection.hst import _extract_features

        event = _make_event()
        features = _extract_features(event)

        assert features["tid_1"] == 1.0
        assert features["entity_count"] == 0.0
        assert features["severity"] == float(SeverityLevel.INFORMATIONAL.value)
        assert features["param_count"] == 0.0
        assert features["msg_length"] == float(len("test message"))

    def test_features_are_all_floats(self) -> None:
        from seerflow.detection.hst import _extract_features

        event = _make_event()
        features = _extract_features(event)

        for key, value in features.items():
            assert isinstance(value, float), f"Feature {key} is {type(value)}, expected float"


# ---------------------------------------------------------------------------
# HSTDetector core tests
# ---------------------------------------------------------------------------


class TestHSTDetector:
    def test_score_returns_float_in_range(self) -> None:
        from seerflow.detection.hst import HSTDetector

        detector = HSTDetector()
        event = _make_event()
        score = detector.score(event)

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_learn_does_not_raise(self) -> None:
        from seerflow.detection.hst import HSTDetector

        detector = HSTDetector()
        event = _make_event()
        detector.learn(event)  # Should not raise

    def test_score_then_learn_pattern(self) -> None:
        """Train on normal events, then verify anomalous event scores higher."""
        from seerflow.detection.hst import HSTDetector

        detector = HSTDetector(n_trees=25, window_size=50, seed=42)

        normal_event = _make_event(
            template_id=1,
            severity_id=SeverityLevel.INFORMATIONAL,
            message="Normal operation completed",
            entity_refs=(),
            template_params=(),
        )

        for _ in range(50):
            detector.score(normal_event)
            detector.learn(normal_event)

        normal_score = detector.score(normal_event)

        anomalous_event = _make_event(
            template_id=999,
            severity_id=SeverityLevel.FATAL,
            message="CRITICAL FAILURE: kernel panic in module xyz with stack overflow and memory corruption detected across multiple subsystems resulting in total system degradation",
            entity_refs=("e1", "e2", "e3", "e4", "e5"),
            template_params=("p1", "p2", "p3", "p4", "p5", "p6", "p7"),
        )
        anomalous_score = detector.score(anomalous_event)

        assert anomalous_score > normal_score, (
            f"Anomalous score ({anomalous_score}) should be higher than "
            f"normal score ({normal_score})"
        )

    def test_configurable_params(self) -> None:
        from seerflow.detection.hst import HSTDetector

        detector = HSTDetector(n_trees=10, window_size=500, seed=123)
        event = _make_event()
        score = detector.score(event)

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_score_clamped_to_unit_interval(self) -> None:
        """Scores should always be in [0.0, 1.0] regardless of raw model output."""
        from seerflow.detection.hst import HSTDetector

        detector = HSTDetector()
        for _ in range(100):
            event = _make_event(
                template_id=uuid.uuid4().int % 10000,
                message="x" * (uuid.uuid4().int % 500),
            )
            score = detector.score(event)
            assert 0.0 <= score <= 1.0
            detector.learn(event)
