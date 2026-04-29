"""Hand-rolled Bloom filter for IoC matching (S-068)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BloomParams:
    """Sizing parameters for a Bloom filter at a target FPR."""

    expected_items: int
    fpr: float

    def __post_init__(self) -> None:
        if not (0.0 < self.fpr < 1.0):
            raise ValueError(f"fpr must be in (0, 1), got {self.fpr!r}")
        if self.expected_items < 1:
            raise ValueError(
                f"expected_items must be >= 1, got {self.expected_items!r}"
            )

    @property
    def bit_count(self) -> int:
        # m = -N * ln(p) / (ln 2)^2
        n = float(self.expected_items)
        return max(1, math.ceil(-n * math.log(self.fpr) / (math.log(2.0) ** 2)))

    @property
    def hash_count(self) -> int:
        # k = round(m/N * ln 2), at least 1
        return max(1, round(self.bit_count / self.expected_items * math.log(2.0)))

    @property
    def byte_size(self) -> int:
        return math.ceil(self.bit_count / 8)


def optimal_params(*, expected_items: int, fpr: float) -> BloomParams:
    """Pure-function helper — returns BloomParams; same as direct construction."""
    return BloomParams(expected_items=expected_items, fpr=fpr)
