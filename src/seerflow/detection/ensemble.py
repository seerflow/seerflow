"""DetectionEnsemble — orchestrates detectors + DSPOT thresholds."""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import msgspec.json

from seerflow.detection.cusum import CUSUMDetector
from seerflow.detection.holtwinters import HoltWintersDetector
from seerflow.detection.hst import HSTDetector
from seerflow.detection.markov import MarkovDetector
from seerflow.detection.threshold import DSpotThreshold

if TYPE_CHECKING:
    from seerflow.config import DetectionConfig
    from seerflow.detection.protocols import Detector
    from seerflow.models import SeerflowEvent
    from seerflow.storage.protocols import ModelStore

_log = logging.getLogger(__name__)


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

    __slots__ = ("_config", "_detectors", "_eviction_count", "_max_sources", "_thresholds")

    _MAX_SOURCES_CEILING = 10_000

    def __init__(self, config: DetectionConfig) -> None:
        if config.max_sources < 1 or config.max_sources > self._MAX_SOURCES_CEILING:
            msg = (
                f"max_sources must be between 1 and {self._MAX_SOURCES_CEILING}, "
                f"got {config.max_sources}"
            )
            raise ValueError(msg)
        self._config = config
        self._max_sources = config.max_sources
        self._detectors: OrderedDict[str, list[Detector]] = OrderedDict()
        self._thresholds: OrderedDict[str, DSpotThreshold] = OrderedDict()
        self._eviction_count: int = 0

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
        if source in self._detectors:
            self._detectors.move_to_end(source)
            return self._detectors[source]
        if len(self._detectors) >= self._max_sources:
            evicted_source, _ = self._detectors.popitem(last=False)
            self._thresholds.pop(evicted_source, None)
            self._eviction_count += 1
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
        """Return (or create) the DSPOT threshold for *source*.

        Eviction is driven by _get_detectors, not here.
        """
        if source in self._thresholds:
            return self._thresholds[source]
        self._thresholds[source] = DSpotThreshold(
            calibration_window=self._config.dspot_calibration_window,
            risk_level=self._config.dspot_risk_level,
            initial_percentile=self._config.dspot_initial_percentile,
        )
        return self._thresholds[source]

    def get_stats(self) -> dict[str, int]:
        """Return operational statistics about the ensemble."""
        return {
            "source_count": len(self._detectors),
            "max_sources": self._max_sources,
            "eviction_count": self._eviction_count,
        }

    async def save_all_state(self, storage: ModelStore) -> int:
        """Serialize all detector + threshold state to storage. Returns count saved."""
        sources = list(self._detectors.keys())
        await storage.save_state(
            "ensemble:manifest",
            msgspec.json.encode(sources),
        )
        count = 0
        for source in sources:
            detectors = self._detectors[source]
            for i, det in enumerate(detectors):
                await storage.save_state(f"det:{source}:{i}", det.serialize())
                count += 1
            thresh = self._thresholds.get(source)
            if thresh is not None:
                await storage.save_state(
                    f"thresh:{source}",
                    thresh.serialize(),
                )
                count += 1
        return count

    async def load_all_state(self, storage: ModelStore) -> int:
        """Restore detector state from storage. Returns count loaded."""
        manifest_bytes = await storage.load_state("ensemble:manifest")
        if manifest_bytes is None:
            return 0
        try:
            sources: list[str] = msgspec.json.decode(
                manifest_bytes,
                type=list[str],
            )
        except Exception:
            _log.warning("Corrupt ensemble manifest — starting fresh")
            return 0
        count = 0
        for source in sources:
            try:
                detectors = self._get_detectors(source)
                for i, det in enumerate(detectors):
                    data = await storage.load_state(f"det:{source}:{i}")
                    if data is not None:
                        try:
                            det.deserialize(data)
                            count += 1
                        except Exception:
                            _log.warning(
                                "Corrupt model state for det:%s:%d — fresh model",
                                source,
                                i,
                            )
                thresh_data = await storage.load_state(f"thresh:{source}")
                if thresh_data is not None:
                    try:
                        self._thresholds[source] = DSpotThreshold.deserialize(
                            thresh_data,
                        )
                        count += 1
                    except Exception:
                        _log.warning(
                            "Corrupt threshold for %s — fresh threshold",
                            source,
                        )
            except Exception:
                _log.warning("Invalid source %r in manifest — skipping", source)
        return count
