"""Tests for HSTDetector — Half-Space Trees anomaly detector."""

from __future__ import annotations

import uuid

import pytest

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
            related_ips=("10.0.0.1", "10.0.0.2"),
            related_users=("admin",),
            severity_id=SeverityLevel.ERROR,
            template_params=("p1", "p2", "p3"),
            message="hello world",
        )
        features = _extract_features(event)

        assert features["tid_42"] == 1.0
        assert features["entity_count"] == 3.0  # 2 IPs + 1 user
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
            message=(
                "CRITICAL FAILURE: kernel panic in module xyz with stack overflow "
                "and memory corruption detected across multiple subsystems"
            ),
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


# ---------------------------------------------------------------------------
# Serialization + Protocol conformance tests
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_serialize_returns_bytes(self) -> None:
        from seerflow.detection.hst import HSTDetector

        detector = HSTDetector()
        event = _make_event()
        detector.learn(event)
        data = detector.serialize()

        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_round_trip_produces_same_scores(self) -> None:
        """Train 20 events, serialize, deserialize, compare scores."""
        from seerflow.detection.hst import HSTDetector

        detector = HSTDetector(n_trees=15, window_size=100, seed=42)

        events = [
            _make_event(
                template_id=i % 3,
                message=f"event number {i}",
                severity_id=SeverityLevel.INFORMATIONAL,
            )
            for i in range(20)
        ]

        for event in events:
            detector.score(event)
            detector.learn(event)

        data = detector.serialize()

        restored = HSTDetector()
        restored.deserialize(data)

        test_event = _make_event(template_id=5, message="new unseen event")
        original_score = detector.score(test_event)
        restored_score = restored.score(test_event)

        assert original_score == pytest.approx(restored_score, abs=1e-10)

    def test_deserialize_empty_raises(self) -> None:
        import pickle

        from seerflow.detection.hst import HSTDetector

        detector = HSTDetector()
        with pytest.raises((pickle.UnpicklingError, EOFError)):
            detector.deserialize(b"")


class TestProtocolConformance:
    def test_hst_implements_detector(self) -> None:
        from seerflow.detection.hst import HSTDetector
        from seerflow.detection.protocols import Detector

        detector = HSTDetector()
        assert isinstance(detector, Detector)


# ---------------------------------------------------------------------------
# Per-source factory tests
# ---------------------------------------------------------------------------


class TestGetHstDetector:
    def test_same_source_returns_same_detector(self) -> None:
        from seerflow.config import DetectionConfig
        from seerflow.detection.hst import HSTDetector, get_hst_detector

        config = DetectionConfig()
        registry: dict[str, HSTDetector] = {}

        d1 = get_hst_detector("syslog", config, registry)
        d2 = get_hst_detector("syslog", config, registry)

        assert d1 is d2

    def test_different_source_returns_different_detector(self) -> None:
        from seerflow.config import DetectionConfig
        from seerflow.detection.hst import HSTDetector, get_hst_detector

        config = DetectionConfig()
        registry: dict[str, HSTDetector] = {}

        d1 = get_hst_detector("syslog", config, registry)
        d2 = get_hst_detector("cloudwatch", config, registry)

        assert d1 is not d2

    def test_uses_config_values(self) -> None:
        from seerflow.config import DetectionConfig
        from seerflow.detection.hst import HSTDetector, get_hst_detector

        config = DetectionConfig(hst_n_trees=10, hst_window_size=500)
        registry: dict[str, HSTDetector] = {}

        detector = get_hst_detector("test_source", config, registry)

        assert detector._model.n_trees == 10
        assert detector._model.window_size == 500

    def test_factory_exported_from_package(self) -> None:
        from seerflow.detection import HSTDetector, get_hst_detector

        assert callable(get_hst_detector)
        assert HSTDetector is not None


class TestHSTUnpickler:
    """Test restricted unpickler rejects disallowed classes (lines 36-37)."""

    def test_rejects_disallowed_class(self) -> None:
        """Unpickler refuses to deserialize a class not in the allowlist."""
        import pickle

        from seerflow.detection.hst import HSTDetector

        # Craft pickle data containing a disallowed class (os.system)
        malicious = pickle.dumps({"key": "value"})  # dict is allowed by default pickle
        # But we can test via the HSTDetector.deserialize path by providing
        # pickle data for a dict (not HalfSpaceTrees)
        detector = HSTDetector()
        with pytest.raises((pickle.UnpicklingError, TypeError)):
            detector.deserialize(malicious)

    def test_rejects_os_system(self) -> None:
        """Unpickler refuses classes like os.system."""
        import io
        import pickle

        from seerflow.detection.hst import _HSTUnpickler

        # Build raw pickle bytes that try to load os.system
        # Using pickle protocol to encode a reference to os.system
        buf = io.BytesIO()
        # GLOBAL opcode: push os.system onto stack
        buf.write(b"\x80\x02cos\nsystem\nq\x00.")  # pickle v2 for os.system
        buf.seek(0)
        with pytest.raises(pickle.UnpicklingError, match="Refused to deserialize"):
            _HSTUnpickler(buf).load()


class TestHSTDeserializeWrongType:
    """Test deserialize with non-HalfSpaceTrees object (lines 89-90)."""

    def test_deserialize_wrong_type_raises_type_error(self) -> None:
        """Deserialize data that decodes to a non-HalfSpaceTrees type raises TypeError."""
        import pickle

        from seerflow.detection.hst import HSTDetector

        # Serialize a tuple (which is in the allowlist) wrapped in bytes
        data = pickle.dumps(("not", "a", "model"))
        detector = HSTDetector()
        with pytest.raises(TypeError, match="Expected HalfSpaceTrees"):
            detector.deserialize(data)
