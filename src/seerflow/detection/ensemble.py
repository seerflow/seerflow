"""DetectionEnsemble — orchestrates detectors + DSPOT thresholds."""

from __future__ import annotations

import logging
import math
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

_MAX_SOURCE_KEY_LEN = 248  # 256 (storage limit) - 8 (longest prefix "windows:")


class _WelfordAccumulator:
    """Online mean/variance via Welford's algorithm. O(1) per update."""

    __slots__ = ("_m2", "_mean", "_n")

    def __init__(self) -> None:
        self._n: int = 0
        self._mean: float = 0.0
        self._m2: float = 0.0

    def update(self, x: float) -> None:
        self._n += 1
        delta = x - self._mean
        self._mean += delta / self._n
        delta2 = x - self._mean
        self._m2 += delta * delta2

    def mean(self) -> float:
        return self._mean

    def stdev(self) -> float:
        if self._n < 2:
            return 0.0
        return math.sqrt(self._m2 / (self._n - 1))

    def to_dict(self) -> dict[str, float | int]:
        return {"n": self._n, "mean": self._mean, "m2": self._m2}

    @staticmethod
    def from_dict(d: dict[str, float | int]) -> _WelfordAccumulator:
        acc = _WelfordAccumulator()
        n = int(d["n"])
        mean = float(d["mean"])
        m2 = float(d["m2"])
        if (
            n < 0
            or m2 < 0.0
            or not math.isfinite(mean)
            or not math.isfinite(m2)
            or (n <= 1 and m2 != 0.0)
        ):
            msg = f"Invalid Welford state: n={n}, mean={mean}, m2={m2}"
            raise ValueError(msg)
        acc._n = n
        acc._mean = mean
        acc._m2 = m2
        return acc


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

    __slots__ = (
        "_config",
        "_detectors",
        "_eviction_count",
        "_max_sources",
        "_score_windows",
        "_thresholds",
        "_weights",
    )

    _MAX_SOURCES_CEILING = 10_000

    def __init__(self, config: DetectionConfig) -> None:
        self._config = config
        self._max_sources = config.max_sources
        self._detectors: OrderedDict[str, list[Detector]] = OrderedDict()
        self._thresholds: OrderedDict[str, DSpotThreshold] = OrderedDict()
        self._eviction_count: int = 0
        self._score_windows: OrderedDict[str, list[_WelfordAccumulator]] = OrderedDict()
        self._weights: tuple[float, ...] = (
            config.weights_content,
            config.weights_volume,
            config.weights_pattern,
            config.weights_sequence,
        )

    def process_event(self, event: SeerflowEvent) -> DetectionResult:
        """Score, learn, and threshold-check a single event."""
        raw_source = (event.source_type or "default").replace("\x00", "")
        source = raw_source[:_MAX_SOURCE_KEY_LEN] or "default"
        detectors = self._get_detectors(source)
        scores = [d.score(event) for d in detectors]
        scores = [s if math.isfinite(s) else 0.0 for s in scores]

        # --- Blended scoring pipeline ---
        # 1. Get/create per-detector score windows for this source
        if source not in self._score_windows:
            self._score_windows[source] = [_WelfordAccumulator() for _ in range(len(detectors))]
        else:
            self._score_windows.move_to_end(source)
        windows = self._score_windows[source]

        # 2. Z-normalize (or use raw during warmup)
        # Compute z-score from historical window BEFORE adding current score
        z_scores: list[float] = []
        for i, raw in enumerate(scores):
            acc = windows[i]
            if acc._n >= 2:
                std = max(acc.stdev(), 1e-10)
                z_scores.append((raw - acc.mean()) / std)
            else:
                z_scores.append(raw)
            acc.update(raw)  # append AFTER normalization

        # 3. Weighted average
        weights = self._weights[: len(z_scores)]
        weight_sum = sum(weights)
        if weight_sum > 0:
            combined = sum(z * w for z, w in zip(z_scores, weights, strict=False)) / weight_sum
        else:
            combined = 0.0

        # 4. Signal amplification
        converging = sum(1 for z in z_scores if z > 1.0)
        if converging >= 3:
            combined *= 2.0
        elif converging >= 2:
            combined *= 1.5
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
            self._score_windows.pop(evicted_source, None)
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
                ema_alpha=self._config.cusum_ema_alpha,
                warmup_buckets=self._config.cusum_warmup_buckets,
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
            window_state = self._score_windows.get(source)
            if window_state is not None:
                await storage.save_state(
                    f"windows:{source}",
                    msgspec.json.encode([acc.to_dict() for acc in window_state]),
                )
                count += 1
        await storage.save_state(
            "ensemble:manifest",
            msgspec.json.encode(sources),
        )
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
            _log.warning("Corrupt ensemble manifest — starting fresh", exc_info=True)
            return 0
        if len(sources) > self._max_sources:
            _log.warning(
                "Manifest has %d sources (max %d) — truncating",
                len(sources),
                self._max_sources,
            )
            sources = sources[: self._max_sources]
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
                                exc_info=True,
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
                            exc_info=True,
                        )
                windows_data = await storage.load_state(f"windows:{source}")
                if windows_data is not None:
                    try:
                        acc_dicts: list[dict[str, float | int]] = msgspec.json.decode(
                            windows_data,
                            type=list[dict[str, float | int]],
                        )
                        self._score_windows[source] = [
                            _WelfordAccumulator.from_dict(d) for d in acc_dicts
                        ]
                        count += 1
                    except Exception:
                        _log.warning(
                            "Corrupt window state for %s — fresh windows",
                            source,
                            exc_info=True,
                        )
            except Exception:
                _log.warning("Invalid source %r in manifest — skipping", source, exc_info=True)
        return count
