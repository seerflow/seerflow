"""Tests for the Detector protocol interface."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.detection.protocols import Detector

if TYPE_CHECKING:
    from seerflow.models import SeerflowEvent


class _ConformingDetector:
    """Minimal detector that satisfies the Detector protocol."""

    def score(self, event: SeerflowEvent) -> float:
        return 0.5

    def learn(self, event: SeerflowEvent) -> None:
        pass

    def serialize(self) -> bytes:
        return b"state"

    def deserialize(self, data: bytes) -> None:
        pass


class _MissingScore:
    """Detector missing the score method."""

    def learn(self, event: SeerflowEvent) -> None:
        pass

    def serialize(self) -> bytes:
        return b""

    def deserialize(self, data: bytes) -> None:
        pass


class _MissingSerialize:
    """Detector missing the serialize method."""

    def score(self, event: SeerflowEvent) -> float:
        return 0.0

    def learn(self, event: SeerflowEvent) -> None:
        pass

    def deserialize(self, data: bytes) -> None:
        pass


class TestDetectorProtocol:
    def test_conforming_class_is_instance(self) -> None:
        detector = _ConformingDetector()
        assert isinstance(detector, Detector)

    def test_missing_score_is_not_instance(self) -> None:
        obj = _MissingScore()
        assert not isinstance(obj, Detector)

    def test_missing_serialize_is_not_instance(self) -> None:
        obj = _MissingSerialize()
        assert not isinstance(obj, Detector)

    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(Detector, "__protocol_attrs__") or hasattr(
            Detector, "_is_runtime_protocol"
        )

    def test_detector_imported_from_detection_package(self) -> None:
        from seerflow.detection import Detector as DetectorFromInit

        assert DetectorFromInit is Detector
