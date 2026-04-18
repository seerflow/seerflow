"""DetectionEnsemble — orchestrates detectors + DSPOT thresholds."""

from __future__ import annotations

import logging
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

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
_MAX_ENTITIES_PER_SCORE = 32  # cap per-event entity work to prevent CPU spikes

# Memory estimation constants (bytes) — approximate per-instance footprint.
_MEM_HST = 51_200  # ~50 KB: River HalfSpaceTrees, 25 trees
_MEM_HW = 12_288  # ~12 KB: 1440 seasonal floats + state
_MEM_CUSUM = 200  # ~200 B: O(1) counters + floats
_MEM_MARKOV_ENTITY = 10_240  # ~10 KB: transition matrix per entity
_MEM_DSPOT = 8_192  # ~8 KB: calibration window + tail state


class ThresholdAdjustResult(NamedTuple):
    """Result of ``DetectionEnsemble.adjust_upper_threshold``.

    * ``applied`` — threshold scaled by the requested factor.
    * ``clamped`` — clamp engaged; ``current_ratio`` equals the cap multiplier.
    * ``not_calibrated`` — no-op; source was never calibrated. ``current_ratio`` is 0.0.
    """

    status: Literal["applied", "clamped", "not_calibrated"]
    current_ratio: float


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
        "_entity_event_counts",
        "_entity_hw",
        "_entity_hw_eviction_count",
        "_event_counters",
        "_eviction_count",
        "_max_entity_hw",
        "_max_sources",
        "_max_template_hw",
        "_min_events_for_scoring",
        "_score_interval",
        "_score_windows",
        "_source_hw_keys",
        "_template_event_counts",
        "_template_hw",
        "_template_hw_eviction_count",
        "_thresholds",
        "_weights",
    )

    def __init__(self, config: DetectionConfig) -> None:
        self._config = config
        self._max_sources = config.max_sources
        self._score_interval = config.score_interval
        self._max_template_hw = config.max_template_hw
        self._max_entity_hw = config.max_entity_hw
        self._min_events_for_scoring = config.min_events_for_scoring
        self._detectors: OrderedDict[str, list[Detector]] = OrderedDict()
        self._thresholds: OrderedDict[str, DSpotThreshold] = OrderedDict()
        self._eviction_count: int = 0
        self._event_counters: dict[str, int] = {}
        self._score_windows: OrderedDict[str, list[_WelfordAccumulator]] = OrderedDict()
        self._template_hw: OrderedDict[str, HoltWintersDetector] = OrderedDict()
        self._entity_hw: OrderedDict[str, HoltWintersDetector] = OrderedDict()
        self._template_event_counts: dict[str, int] = {}
        self._entity_event_counts: dict[str, int] = {}
        self._template_hw_eviction_count: int = 0
        self._entity_hw_eviction_count: int = 0
        self._source_hw_keys: dict[str, tuple[set[str], set[str]]] = {}
        self._weights: tuple[float, ...] = (
            config.weights_content,
            config.weights_volume,
            config.weights_pattern,
            config.weights_sequence,
            config.weights_template_volume,
            config.weights_entity_volume,
        )

    def process_event(self, event: SeerflowEvent) -> DetectionResult:
        """Score, learn, and threshold-check a single event."""
        raw_source = (event.source_type or "default").replace("\x00", "").replace(":", "_")
        source = raw_source[:_MAX_SOURCE_KEY_LEN] or "default"

        # Batch scoring: skip scoring for non-Nth events
        self._event_counters[source] = self._event_counters.get(source, 0) + 1
        if self._score_interval > 1 and self._event_counters[source] % self._score_interval != 0:
            return DetectionResult(
                score=0.0,
                upper_threshold=0.0,
                lower_threshold=0.0,
                is_anomaly=False,
                anomaly_direction=None,
                source_type=source,
            )

        detectors = self._get_detectors(source)
        scores = [d.score(event) for d in detectors]
        scores = [s if math.isfinite(s) else 0.0 for s in scores]

        template_score = self._score_template_hw(source, event)
        entity_score = self._score_entity_hw(source, event)
        scores = [
            *scores,
            # nan is intentional (warmup sentinel) — preserved for z-norm filter at step 2.
            # Only ±inf (unexpected overflow) is clamped to 0.0.
            template_score if not math.isinf(template_score) else 0.0,
            entity_score if not math.isinf(entity_score) else 0.0,
        ]

        # --- Blended scoring pipeline ---
        # 1. Get/create per-detector score windows for this source
        if source not in self._score_windows:
            self._score_windows[source] = [
                _WelfordAccumulator() for _ in range(len(self._weights))
            ]
        else:
            self._score_windows.move_to_end(source)
        windows = self._score_windows[source]

        # 2. Z-normalize (or use raw during warmup)
        # Compute z-score from historical window BEFORE adding current score
        z_scores: list[float] = []
        for i, raw in enumerate(scores):
            if math.isnan(raw):
                z_scores.append(float("nan"))
                continue
            acc = windows[i]
            if acc._n >= 2:
                std = max(acc.stdev(), 1e-10)
                z_scores.append((raw - acc.mean()) / std)
            else:
                z_scores.append(raw)
            acc.update(raw)  # append AFTER normalization

        # 3. Weighted average (skip nan — warmup channels)
        weights = self._weights[: len(z_scores)]
        active_pairs = [
            (z, w) for z, w in zip(z_scores, weights, strict=False) if not math.isnan(z)
        ]
        weight_sum = sum(w for _, w in active_pairs)
        combined = sum(z * w for z, w in active_pairs) / weight_sum if weight_sum > 0 else 0.0

        # 4. Signal amplification -- thresholds scale with detector count:
        # 2x when >=2/3 converge, 1.5x when >=1/2 converge
        active_z = [z for z in z_scores if not math.isnan(z)]
        n_signals = len(active_z)
        converging = sum(1 for z in active_z if z > 1.0)
        if converging >= max(n_signals * 2 // 3, 2):
            combined *= 2.0
        elif converging >= max(n_signals // 2, 2):
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
            self._event_counters.pop(evicted_source, None)
            self._eviction_count += 1
            # O(k) cleanup via reverse index: k = HW keys owned by evicted source.
            tmpl_keys, ent_keys = self._source_hw_keys.pop(evicted_source, (set(), set()))
            for key in tmpl_keys:
                self._template_hw.pop(key, None)
                self._template_event_counts.pop(key, None)
            for key in ent_keys:
                self._entity_hw.pop(key, None)
                self._entity_event_counts.pop(key, None)
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

    def _score_template_hw(self, source: str, event: SeerflowEvent) -> float:
        """Score and learn template-level volume anomaly."""
        tid = event.template_id
        if tid < 0:
            return float("nan")
        key = f"{source}:{tid}"[:_MAX_SOURCE_KEY_LEN]
        self._template_event_counts[key] = self._template_event_counts.get(key, 0) + 1
        hw, evicted = self._get_or_create_hw(
            key, self._template_hw, self._template_event_counts, self._max_template_hw
        )
        # setdefault returns existing bucket on cache-hit; index 0 = template set.
        tmpl_set, _ = self._source_hw_keys.setdefault(source, (set(), set()))
        tmpl_set.add(key)
        if evicted:
            self._template_hw_eviction_count += 1
        if self._template_event_counts[key] >= self._min_events_for_scoring:
            raw = hw.score(event)
            score = raw if math.isfinite(raw) else float("nan")
        else:
            score = float("nan")
        hw.learn(event)
        return score

    def _score_entity_hw(self, source: str, event: SeerflowEvent) -> float:
        """Score and learn entity-level volume anomaly (max across entities)."""
        if not event.entity_refs:
            return float("nan")
        max_score = float("nan")
        for entity_val in event.entity_refs[:_MAX_ENTITIES_PER_SCORE]:
            safe_val = entity_val.replace("\x00", "").replace(":", "_")
            if not safe_val:
                continue
            key = f"{source}:{safe_val}"[:_MAX_SOURCE_KEY_LEN]
            self._entity_event_counts[key] = self._entity_event_counts.get(key, 0) + 1
            hw, evicted = self._get_or_create_hw(
                key, self._entity_hw, self._entity_event_counts, self._max_entity_hw
            )
            # setdefault returns existing bucket on cache-hit; index 1 = entity set.
            _, ent_set = self._source_hw_keys.setdefault(source, (set(), set()))
            ent_set.add(key)
            if evicted:
                self._entity_hw_eviction_count += 1
            if self._entity_event_counts[key] >= self._min_events_for_scoring:
                raw = hw.score(event)
                score = raw if math.isfinite(raw) else float("nan")
            else:
                score = float("nan")
            hw.learn(event)
            if math.isnan(max_score) or score > max_score:
                max_score = score
        return max_score

    def _get_or_create_hw(
        self,
        key: str,
        hw_dict: OrderedDict[str, HoltWintersDetector],
        counts_dict: dict[str, int],
        max_items: int,
    ) -> tuple[HoltWintersDetector, bool]:
        """Return (or create) an HW detector in the given pool with LRU eviction.

        Pools are also eagerly cleaned on source eviction in ``_get_detectors``
        via the per-source reverse index (``_source_hw_keys.pop(source)``).

        Returns a ``(detector, evicted)`` tuple where *evicted* is ``True``
        when adding the new key required evicting the LRU entry.
        """
        if key in hw_dict:
            hw_dict.move_to_end(key)
            return hw_dict[key], False
        evicted = False
        if len(hw_dict) >= max_items:
            evicted_key, _ = hw_dict.popitem(last=False)
            counts_dict.pop(evicted_key, None)
            evicted_owner = evicted_key.split(":", 1)[0]
            owner_entry = self._source_hw_keys.get(evicted_owner)
            if owner_entry is not None:
                idx = 0 if hw_dict is self._template_hw else 1
                owner_entry[idx].discard(evicted_key)
            evicted = True
        hw = HoltWintersDetector(
            seasonal_period=self._config.hw_seasonal_period,
            alpha=self._config.hw_alpha,
            beta=self._config.hw_beta,
            gamma=self._config.hw_gamma,
            n_std=self._config.hw_n_std,
        )
        hw_dict[key] = hw
        return hw, evicted

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
            cap_multiplier=self._config.dspot_threshold_cap_multiplier,
        )
        return self._thresholds[source]

    def adjust_upper_threshold(self, source_key: str, factor: float) -> ThresholdAdjustResult:
        """Adjust DSPOT upper threshold for *source_key*.

        Returns a ``ThresholdAdjustResult`` describing whether the adjustment
        was applied cleanly, clamped by the cap, or skipped because the
        source is not yet calibrated.
        """
        dspot = self._thresholds.get(source_key)
        if dspot is None or not dspot.is_calibrated:
            return ThresholdAdjustResult(status="not_calibrated", current_ratio=0.0)
        was_clamped, ratio = dspot.adjust_upper_threshold(factor)
        if was_clamped:
            safe_key = source_key[:64]
            _log.warning(
                "DSPOT threshold capped at %.2fx baseline for source %r "
                "(factor=%.3f rejected; review detector for noise)",
                ratio,
                safe_key,
                factor,
            )
            return ThresholdAdjustResult(status="clamped", current_ratio=ratio)
        return ThresholdAdjustResult(status="applied", current_ratio=ratio)

    def get_upper_threshold(self, source_key: str) -> float:
        """Get current DSPOT upper threshold for a source. Returns 0.0 if not found."""
        dspot = self._thresholds.get(source_key)
        if dspot is None or not dspot.is_calibrated:
            return 0.0
        return dspot.threshold

    def get_stats(self) -> dict[str, int]:
        """Return operational statistics about the ensemble."""
        return {
            "source_count": len(self._detectors),
            "max_sources": self._max_sources,
            "eviction_count": self._eviction_count,
            "template_hw_count": len(self._template_hw),
            "entity_hw_count": len(self._entity_hw),
        }

    def get_health(self) -> dict[str, Any]:
        """Return health stats with memory estimation and Markov entity counts."""
        stats = self.get_stats()
        source_count = stats["source_count"]

        # Markov entity counts per source
        markov_entity_counts: dict[str, int] = {}
        total_markov_entities = 0
        for source, detectors in self._detectors.items():
            for d in detectors:
                if isinstance(d, MarkovDetector):
                    count = d.entity_count
                    markov_entity_counts[source] = count
                    total_markov_entities += count

        # Memory by type
        mem_hst = source_count * _MEM_HST
        mem_hw_source = source_count * _MEM_HW
        mem_hw_template = stats["template_hw_count"] * _MEM_HW
        mem_hw_entity = stats["entity_hw_count"] * _MEM_HW
        mem_cusum = source_count * _MEM_CUSUM
        mem_markov = total_markov_entities * _MEM_MARKOV_ENTITY
        mem_dspot = len(self._thresholds) * _MEM_DSPOT

        memory_by_type = {
            "hst": mem_hst,
            "hw_source": mem_hw_source,
            "hw_template": mem_hw_template,
            "hw_entity": mem_hw_entity,
            "cusum": mem_cusum,
            "markov": mem_markov,
            "dspot": mem_dspot,
        }

        return {
            **stats,
            "template_hw_eviction_count": self._template_hw_eviction_count,
            "entity_hw_eviction_count": self._entity_hw_eviction_count,
            "estimated_memory_bytes": sum(memory_by_type.values()),
            "memory_by_type": memory_by_type,
            "markov_entity_counts": markov_entity_counts,
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
        # Persist template HW instances
        tmpl_keys = list(self._template_hw.keys())
        for key in tmpl_keys:
            hw = self._template_hw[key]
            await storage.save_state(f"tmpl_hw:{key}", hw.serialize())
            count += 1
        # Persist entity HW instances
        ent_keys = list(self._entity_hw.keys())
        for key in ent_keys:
            hw = self._entity_hw[key]
            await storage.save_state(f"ent_hw:{key}", hw.serialize())
            count += 1
        # Write all manifests last — crash-safety: partial data is ignored
        # on load when the manifest is missing
        await storage.save_state(
            "tmpl_hw:manifest",
            msgspec.json.encode({k: self._template_event_counts.get(k, 0) for k in tmpl_keys}),
        )
        await storage.save_state(
            "ent_hw:manifest",
            msgspec.json.encode({k: self._entity_event_counts.get(k, 0) for k in ent_keys}),
        )
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
                            cap_multiplier=self._config.dspot_threshold_cap_multiplier,
                            source_key=source,
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
                        accs = [_WelfordAccumulator.from_dict(d) for d in acc_dicts]
                        if len(accs) < len(self._weights):
                            accs.extend(
                                _WelfordAccumulator()
                                for _ in range(len(self._weights) - len(accs))
                            )
                        self._score_windows[source] = accs
                        count += 1
                    except Exception:
                        _log.warning(
                            "Corrupt window state for %s — fresh windows",
                            source,
                            exc_info=True,
                        )
            except Exception:
                _log.warning("Invalid source %r in manifest — skipping", source, exc_info=True)
        count += await self._load_granular_hw(
            storage,
            "tmpl_hw",
            self._template_hw,
            self._template_event_counts,
            self._max_template_hw,
        )
        count += await self._load_granular_hw(
            storage,
            "ent_hw",
            self._entity_hw,
            self._entity_event_counts,
            self._max_entity_hw,
        )
        return count

    async def _load_granular_hw(
        self,
        storage: ModelStore,
        prefix: str,
        hw_dict: OrderedDict[str, HoltWintersDetector],
        counts_dict: dict[str, int],
        max_items: int,
    ) -> int:
        """Load per-template or per-entity HW state from storage."""
        manifest_bytes = await storage.load_state(f"{prefix}:manifest")
        if manifest_bytes is None:
            return 0
        try:
            manifest: dict[str, int] = msgspec.json.decode(
                manifest_bytes,
                type=dict[str, int],
            )
        except Exception:
            _log.warning("Corrupt %s manifest — skipping", prefix, exc_info=True)
            return 0
        loaded = 0
        idx = 0 if hw_dict is self._template_hw else 1
        # Reverse: manifest preserves LRU order (oldest first from OrderedDict),
        # so load MRU entries first to keep the hottest keys when capacity-limited.
        for raw_key, evt_count in list(manifest.items())[-max_items:]:
            if not isinstance(evt_count, int) or evt_count < 0:
                _log.warning(
                    "Invalid event count %r for %s:%s — skipping",
                    evt_count,
                    prefix,
                    raw_key,
                )
                continue
            # Re-apply sanitizer so legacy colon-laden sources collapse.
            # Keys have format "{source}:{id}". Sanitize the source segment only
            # (rsplit to isolate the rightmost colon as the separator).
            if ":" in raw_key:
                src_part, suffix = raw_key.rsplit(":", 1)
                src_part = src_part.replace("\x00", "").replace(":", "_")
                suffix = suffix.replace("\x00", "")
                sanitized_key = f"{src_part}:{suffix}"
            else:
                sanitized_key = raw_key.replace("\x00", "")
            if sanitized_key in hw_dict:
                _log.warning(
                    "Duplicate %s key after sanitization — keeping first (sanitized=%r raw=%r)",
                    prefix,
                    sanitized_key[:64],
                    raw_key[:64],
                )
                continue
            data = await storage.load_state(f"{prefix}:{raw_key}")
            if data is None:
                continue
            try:
                hw = HoltWintersDetector(
                    seasonal_period=self._config.hw_seasonal_period,
                    alpha=self._config.hw_alpha,
                    beta=self._config.hw_beta,
                    gamma=self._config.hw_gamma,
                    n_std=self._config.hw_n_std,
                )
                hw.deserialize(data)
                hw_dict[sanitized_key] = hw
                counts_dict[sanitized_key] = evt_count
                owning_source = sanitized_key.split(":", 1)[0]
                bucket = self._source_hw_keys.setdefault(owning_source, (set(), set()))
                bucket[idx].add(sanitized_key)
                loaded += 1
            except Exception:
                _log.warning(
                    "Corrupt %s state for %s — skipping",
                    prefix,
                    sanitized_key,
                    exc_info=True,
                )
        return loaded
