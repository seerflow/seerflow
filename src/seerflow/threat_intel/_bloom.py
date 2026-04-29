"""Hand-rolled Bloom filter for IoC matching (S-068)."""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class BloomParams:
    """Sizing parameters for a Bloom filter at a target FPR."""

    expected_items: int
    fpr: float

    def __post_init__(self) -> None:
        if not (0.0 < self.fpr < 1.0):
            raise ValueError(f"fpr must be in (0, 1), got {self.fpr!r}")
        if self.expected_items < 1:
            raise ValueError(f"expected_items must be >= 1, got {self.expected_items!r}")

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


class _BloomFilter:
    """Fixed-size bit-array Bloom filter, immutable after construction."""

    __slots__ = ("_bits", "_byte_size", "_k", "_m")

    def __init__(self, bits: bytearray, m: int, k: int) -> None:
        # Constructor is private; callers use ``from_values``. The signature
        # is kept narrow so we don't accidentally expose a public mutator.
        self._bits = bits
        self._m = m
        self._k = k
        self._byte_size = len(bits)

    @classmethod
    def from_values(cls, values: Iterable[str], params: BloomParams) -> _BloomFilter:
        bits = bytearray(params.byte_size)
        m = params.bit_count
        k = params.hash_count
        for v in values:
            cls._set(bits, m, k, v)
        return cls(bits, m, k)

    def __contains__(self, value: str) -> bool:
        h1, h2 = self._hash_pair(value)
        for i in range(self._k):
            idx = (h1 + i * h2) % self._m
            if not (self._bits[idx >> 3] >> (idx & 7)) & 1:
                return False
        return True

    @property
    def byte_size(self) -> int:
        return self._byte_size

    @property
    def bit_count(self) -> int:
        return self._m

    @property
    def hash_count(self) -> int:
        return self._k

    @staticmethod
    def _hash_pair(value: str) -> tuple[int, int]:
        digest = hashlib.blake2b(value.encode("utf-8"), digest_size=16).digest()
        h1, h2 = struct.unpack("<QQ", digest)
        return h1, h2

    @classmethod
    def _set(cls, bits: bytearray, m: int, k: int, value: str) -> None:
        h1, h2 = cls._hash_pair(value)
        for i in range(k):
            idx = (h1 + i * h2) % m
            bits[idx >> 3] |= 1 << (idx & 7)
