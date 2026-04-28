"""Branch coverage tests for STIXIndicatorParser internals (S-067).

Targets the missing branches identified in coverage:
- ``_walk`` top-level comparison branch (115-116).
- ``_walk_comparison`` operands recursion branch (123-125).
- ``_walk_comparison`` early-return on missing path / rhs (130).
- ``_walk_comparison`` early-return on missing rhs.value (140).
- ``_walk_comparison`` unmapped hash kind (145->147).
- ``_walk_comparison`` unmapped object_type/path (151->exit).
- ``_to_ns`` falsy / datetime / non-str-non-datetime branches (160-165).
- ``parse`` kill_chain phase missing ``phase_name``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from seerflow.threat_intel.stix_parser import (
    STIXIndicatorParser,
    _extract_leaves,
    _to_ns,
)

# --- _to_ns ---------------------------------------------------------------


def test_to_ns_returns_none_for_falsy() -> None:
    assert _to_ns(None) is None
    assert _to_ns("") is None
    assert _to_ns(0) is None


def test_to_ns_returns_none_for_unsupported_type() -> None:
    """Cover line 163 -- non-str, non-datetime."""
    assert _to_ns(12345) is None
    assert _to_ns([1, 2, 3]) is None


def test_to_ns_handles_aware_datetime() -> None:
    dt = datetime(2026, 1, 1, tzinfo=UTC)
    expected = int(dt.timestamp() * 1_000_000_000)
    assert _to_ns(dt) == expected


def test_to_ns_handles_naive_datetime_assumes_utc() -> None:
    """Cover line 165 -- naive datetime is reinterpreted as UTC."""
    naive = datetime(2026, 1, 1)
    aware = naive.replace(tzinfo=UTC)
    assert _to_ns(naive) == int(aware.timestamp() * 1_000_000_000)


def test_to_ns_handles_iso_string() -> None:
    assert _to_ns("2026-01-01T00:00:00Z") == _to_ns(datetime(2026, 1, 1, tzinfo=UTC))


# --- _walk / _walk_comparison via fake AST nodes -------------------------


def _cmp(obj_type: str, prop: str, value: Any) -> SimpleNamespace:
    """Build a fake comparison node with lhs / rhs."""
    path = SimpleNamespace(
        object_type_name=obj_type,
        property_path=[SimpleNamespace(property_name=prop)],
    )
    rhs = SimpleNamespace(value=value)
    return SimpleNamespace(lhs=path, rhs=rhs)


def _hash_cmp(hash_kind: str, value: Any) -> SimpleNamespace:
    path = SimpleNamespace(
        object_type_name="file",
        property_path=[
            SimpleNamespace(property_name="hashes"),
            SimpleNamespace(property_name=hash_kind),
        ],
    )
    rhs = SimpleNamespace(value=value)
    return SimpleNamespace(lhs=path, rhs=rhs)


def test_walk_top_level_comparison_node() -> None:
    """Cover lines 115-116 -- node already a comparison expression."""
    node = _cmp("ipv4-addr", "value", "9.9.9.9")
    leaves = _extract_leaves(node)
    assert leaves == [("ipv4", "9.9.9.9")]


def test_walk_comparison_recurses_into_operands() -> None:
    """Cover lines 123-125 -- AND / OR over comparisons."""
    cmp_node = SimpleNamespace(
        operands=[
            _cmp("ipv4-addr", "value", "1.1.1.1"),
            _cmp("domain-name", "value", "evil.example"),
        ],
    )
    # Wrap so _walk dispatches into _walk_comparison via .operand.
    obs = SimpleNamespace(operand=cmp_node)
    leaves = _extract_leaves(obs)
    assert ("ipv4", "1.1.1.1") in leaves
    assert ("domain", "evil.example") in leaves


def test_walk_comparison_returns_when_lhs_missing() -> None:
    """Cover line 130 -- path None or rhs None."""
    cmp_node = SimpleNamespace(lhs=None, rhs=SimpleNamespace(value="x"))
    obs = SimpleNamespace(operand=cmp_node)
    assert _extract_leaves(obs) == []


def test_walk_comparison_returns_when_rhs_missing() -> None:
    """Cover line 130 -- rhs branch."""
    cmp_node = SimpleNamespace(
        lhs=SimpleNamespace(object_type_name="ipv4-addr", property_path=[]),
        rhs=None,
    )
    obs = SimpleNamespace(operand=cmp_node)
    assert _extract_leaves(obs) == []


def test_walk_comparison_returns_when_value_missing() -> None:
    """Cover line 140 -- rhs.value is None."""
    cmp_node = _cmp("ipv4-addr", "value", None)
    obs = SimpleNamespace(operand=cmp_node)
    assert _extract_leaves(obs) == []


def test_walk_comparison_skips_unmapped_hash_kind() -> None:
    """Cover line 145->147 -- hash kind absent from _HASH_NAME_MAP."""
    cmp_node = _hash_cmp("CRC32", "deadbeef")
    obs = SimpleNamespace(operand=cmp_node)
    assert _extract_leaves(obs) == []


def test_walk_comparison_skips_unmapped_object_type() -> None:
    """Cover line 151->exit -- type_key not in _PATH_TYPE_MAP."""
    cmp_node = _cmp("process", "name", "evil.exe")
    obs = SimpleNamespace(operand=cmp_node)
    assert _extract_leaves(obs) == []


def test_walk_comparison_handles_file_hashes_no_property() -> None:
    """Edge case -- file:hashes path with empty property tail returns
    cleanly via the strip + lookup miss branch."""
    path = SimpleNamespace(
        object_type_name="file",
        property_path=[SimpleNamespace(property_name="hashes")],
    )
    cmp_node = SimpleNamespace(lhs=path, rhs=SimpleNamespace(value="x"))
    obs = SimpleNamespace(operand=cmp_node)
    assert _extract_leaves(obs) == []


# --- parse() integration with kill chain branch --------------------------


def test_parse_skips_non_dict_kill_chain_phase_entries() -> None:
    parser = STIXIndicatorParser()
    sdo = {
        "type": "indicator",
        "id": "indicator--00000000-0000-0000-0000-00000000ffff",
        "pattern": "[ipv4-addr:value = '5.6.7.8']",
        "valid_from": "2026-01-01T00:00:00Z",
        # Mix dict-with-name, dict-without-name, and a non-dict entry.
        "kill_chain_phases": [
            {"kill_chain_name": "lm", "phase_name": "delivery"},
            {"kill_chain_name": "lm"},  # missing phase_name -> dropped.
            "not-a-dict",  # filtered out by isinstance check.
        ],
    }
    out = parser.parse(sdo, source_feed="t")
    assert len(out) == 1
    # Only the dict entry with a non-empty phase_name survives — empty
    # strings are dropped so downstream consumers don't see noisy phantoms.
    assert out[0].kill_chain_phases == ("delivery",)
