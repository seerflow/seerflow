"""DetectionEnsemble — orchestrates detectors + DSPOT thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from seerflow.detection.cusum import CUSUMDetector
from seerflow.detection.holtwinters import HoltWintersDetector
from seerflow.detection.hst import HSTDetector
from seerflow.detection.markov import MarkovDetector
from seerflow.detection.threshold import DSpotThreshold

if TYPE_CHECKING:
    from seerflow.config import DetectionConfig
    from seerflow.detection.protocols import Detector
    from seerflow.models import SeerflowEvent


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Result from the detection ensemble for a single event."""

    score: float
    upper_threshold: float
    lower_threshold: float
    is_anomaly: bool
    anomaly_direction: Literal["upper", "lower"] | None
    source_type: str


class DetectionEnsemble:
    """Orchestrates multiple detectors and DSPOT thresholds per source.

    NOT thread-safe — designed for single event-loop operation.
    Per-source detector and threshold instances are created lazily
    on first event for each source_type.
    """

    __slots__ = ("_config", "_detectors", "_thresholds")

    def __init__(self, config: DetectionConfig) -> None:
        self._config = config
        self._detectors: dict[str, list[Detector]] = {}
        self._thresholds: dict[str, DSpotThreshold] = {}

    def process_event(self, event: SeerflowEvent) -> DetectionResult:
        """Score, learn, and threshold-check a single event."""
        source = event.source_type or "default"
        detectors = self._get_detectors(source)
        scores = [d.score(event) for d in detectors]
        combined = sum(scores) / len(scores) if scores else 0.0
        for d in detectors:
            d.learn(event)
        threshold = self._get_threshold(source)
        t_result = threshold.update(combined)
        return DetectionResult(
            score=combined,
            upper_threshold=t_result.upper_threshold,
            lower_threshold=t_result.lower_threshold,
            is_anomaly=t_result.is_anomaly,
            anomaly_direction=t_result.anomaly_direction,
            source_type=source,
        )

    def _get_detectors(self, source: str) -> list[Detector]:
        """Return (or create) the detector list for *source*."""
        if source not in self._detectors:
            self._detectors[source] = [
                HSTDetector(
                    n_trees=self._config.hst_n_trees,
                    window_size=self._config.hst_window_size,
                ),
                HoltWintersDetector(
                    seasonal_period=self._config.hw_seasonal_period,
                    alpha=self._config.hw_alpha,
                    beta=self._config.hw_beta,
                    gamma=self._config.hw_gamma,
                    n_std=self._config.hw_n_std,
                ),
                CUSUMDetector(
                    drift=self._config.cusum_drift,
                    threshold=self._config.cusum_threshold,
                ),
                MarkovDetector(
                    smoothing=self._config.markov_smoothing,
                    min_events=self._config.markov_min_events,
                    max_entities=self._config.markov_max_entities,
                ),
            ]
        return self._detectors[source]

    def _get_threshold(self, source: str) -> DSpotThreshold:
        """Return (or create) the DSPOT threshold for *source*."""
        if source not in self._thresholds:
            self._thresholds[source] = DSpotThreshold(
                calibration_window=self._config.dspot_calibration_window,
                risk_level=self._config.dspot_risk_level,
                initial_percentile=self._config.dspot_initial_percentile,
            )
        return self._thresholds[source]
