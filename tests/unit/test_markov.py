"""Tests for MarkovDetector — sequence anomaly detection."""

from __future__ import annotations

import uuid

import pytest

from seerflow.models import SeerflowEvent, SeverityLevel


def _make_event(
    *,
    template_id: int = 1,
    entity_refs: tuple[str, ...] = ("user-001",),
    source_type: str = "syslog",
) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        message="test",
        source_type=source_type,
        template_id=template_id,
        entity_refs=entity_refs,
        severity_id=SeverityLevel.INFORMATIONAL,
    )


class TestMarkovDetector:
    def test_score_returns_float_in_range(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        detector = MarkovDetector()
        score = detector.score(_make_event())
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_score_returns_zero_during_warmup(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        detector = MarkovDetector(min_events=50)
        # Train with 20 events (below warmup)
        for i in range(20):
            tid = (i % 3) + 1
            detector.learn(_make_event(template_id=tid))
        score = detector.score(_make_event(template_id=1))
        assert score == 0.0

    def test_known_transition_scores_low(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        detector = MarkovDetector(min_events=10)
        # Train: 1→2→3→1→2→3 pattern (repeated)
        for _ in range(20):
            for tid in [1, 2, 3]:
                detector.learn(_make_event(template_id=tid))
        # Score a known transition (3→1)
        detector.learn(_make_event(template_id=3))
        known_score = detector.score(_make_event(template_id=1))
        assert known_score < 0.5  # well-known transition should score low

    def test_novel_transition_scores_high(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        detector = MarkovDetector(min_events=10)
        # Train: 1→2→3→1→2→3 pattern
        for _ in range(20):
            for tid in [1, 2, 3]:
                detector.learn(_make_event(template_id=tid))
        # Score a novel transition (1→99, never seen)
        detector.learn(_make_event(template_id=1))
        novel_score = detector.score(_make_event(template_id=99))
        assert novel_score > 0.5  # unseen transition should score high

    def test_novel_higher_than_known(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        detector = MarkovDetector(min_events=10)
        for _ in range(20):
            for tid in [1, 2, 3]:
                detector.learn(_make_event(template_id=tid))

        # Known transition
        detector.learn(_make_event(template_id=3))
        known_score = detector.score(_make_event(template_id=1))

        # Novel transition
        detector.learn(_make_event(template_id=1))
        novel_score = detector.score(_make_event(template_id=99))

        assert novel_score > known_score

    def test_skip_template_id_negative_one(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        detector = MarkovDetector(min_events=5)
        # Train normally
        for _ in range(10):
            detector.learn(_make_event(template_id=1))
            detector.learn(_make_event(template_id=2))
        # template_id=-1 should return 0.0 and not update model
        score = detector.score(_make_event(template_id=-1))
        assert score == 0.0

    def test_skip_no_entity(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        detector = MarkovDetector(min_events=5)
        for _ in range(10):
            detector.learn(_make_event(template_id=1, entity_refs=()))
        # No entity → score 0.0
        score = detector.score(_make_event(template_id=1, entity_refs=()))
        assert score == 0.0

    def test_lru_eviction(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        detector = MarkovDetector(max_entities=3, min_events=2)
        # Create models for 4 entities (exceeds max_entities=3)
        for i in range(4):
            entity = f"entity-{i}"
            for tid in [1, 2]:
                detector.learn(_make_event(template_id=tid, entity_refs=(entity,)))
        # entity-0 should have been evicted (oldest)
        assert "entity-0" not in detector._models
        assert "entity-3" in detector._models

    def test_implements_detector_protocol(self) -> None:
        from seerflow.detection.markov import MarkovDetector
        from seerflow.detection.protocols import Detector

        detector = MarkovDetector()
        assert isinstance(detector, Detector)

    def test_serialize_deserialize_round_trip(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        detector = MarkovDetector(min_events=5, max_entities=10)
        # Train with some data
        for _ in range(10):
            for tid in [1, 2, 3]:
                detector.learn(_make_event(template_id=tid))

        data = detector.serialize()
        assert isinstance(data, bytes)

        restored = MarkovDetector(min_events=5, max_entities=10)
        restored.deserialize(data)

        # Both should produce the same score
        detector.learn(_make_event(template_id=3))
        restored.learn(_make_event(template_id=3))
        assert detector.score(_make_event(template_id=1)) == pytest.approx(
            restored.score(_make_event(template_id=1)), abs=1e-10
        )

    def test_config_parameters_affect_state(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        d1 = MarkovDetector(smoothing=1e-3, min_events=50)
        d2 = MarkovDetector(smoothing=1e-9, min_events=200)
        assert d1._smoothing != d2._smoothing
        assert d1._min_events != d2._min_events

    def test_invalid_smoothing_raises(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        with pytest.raises(ValueError, match="smoothing must be positive"):
            MarkovDetector(smoothing=0.0)

    def test_invalid_min_events_raises(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        with pytest.raises(ValueError, match="min_events must be >= 1"):
            MarkovDetector(min_events=0)

    def test_invalid_max_entities_raises(self) -> None:
        from seerflow.detection.markov import MarkovDetector

        with pytest.raises(ValueError, match="max_entities must be >= 1"):
            MarkovDetector(max_entities=0)
