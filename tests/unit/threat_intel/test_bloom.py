"""Unit tests for _bloom.BloomParams + optimal_params."""

from __future__ import annotations

import math

import pytest

from seerflow.threat_intel._bloom import BloomParams, optimal_params


def test_bloom_params_validates_fpr() -> None:
    with pytest.raises(ValueError, match="fpr"):
        BloomParams(expected_items=1_000, fpr=0.0)
    with pytest.raises(ValueError, match="fpr"):
        BloomParams(expected_items=1_000, fpr=1.0)


def test_bloom_params_validates_expected_items() -> None:
    with pytest.raises(ValueError, match="expected_items"):
        BloomParams(expected_items=0, fpr=0.01)


def test_optimal_params_for_spec_target() -> None:
    p = optimal_params(expected_items=1_000_000, fpr=0.001)
    # m = -N * ln(p) / (ln 2)^2 ≈ 14_377_587 bits
    assert 14_300_000 <= p.bit_count <= 14_500_000
    # Bit array fits inside the 10 MB ceiling at the spec target.
    assert p.bit_count // 8 <= 10 * 1024 * 1024
    # k = round(m/N * ln 2) = 10
    assert p.hash_count == 10


def test_optimal_params_minimum_hash_count() -> None:
    p = optimal_params(expected_items=1, fpr=0.5)
    assert p.hash_count >= 1


def test_bloom_params_byte_size_matches_bit_count() -> None:
    p = BloomParams(expected_items=1_000, fpr=0.01)
    assert p.byte_size == math.ceil(p.bit_count / 8)
