"""STIX 2.1 indicator parser.

Walks the compiled stix2 ``_Pattern`` AST and extracts leaf observables.
Hostile / malformed input is logged and skipped — never raised at the
caller, because one bad SDO must not take down the consumer.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from stix2 import pattern_visitor as _pv  # type: ignore[import-untyped]

from seerflow.models.indicator import Indicator, IndicatorType

_log = logging.getLogger("seerflow")

_MAX_PATTERN_LEN = 4096

# STIX object-path -> IndicatorType (lower-case canonical form).
_PATH_TYPE_MAP: dict[tuple[str, ...], IndicatorType] = {
    ("ipv4-addr", "value"): "ipv4",
    ("ipv6-addr", "value"): "ipv6",
    ("domain-name", "value"): "domain",
    ("url", "value"): "url",
}

_HASH_NAME_MAP: dict[str, IndicatorType] = {
    "md5": "md5",
    "sha-1": "sha1",
    "sha1": "sha1",
    "sha-256": "sha256",
    "sha256": "sha256",
}


class STIXIndicatorParser:
    """Parser for STIX 2.1 ``indicator`` SDOs."""

    def parse(self, sdo: dict[str, Any], *, source_feed: str) -> tuple[Indicator, ...]:
        if sdo.get("type") != "indicator":
            return ()

        pattern = sdo.get("pattern", "")
        if not isinstance(pattern, str) or len(pattern) > _MAX_PATTERN_LEN:
            _log.warning(
                "stix_parser: pattern rejected (len=%d, id=%s)",
                len(pattern) if isinstance(pattern, str) else -1,
                sdo.get("id"),
            )
            return ()

        try:
            tree = _pv.create_pattern_object(pattern, version="2.1")
            leaves = _extract_leaves(tree)
        except Exception as exc:
            _log.warning("stix_parser: pattern walk failed id=%s: %r", sdo.get("id"), exc)
            return ()

        confidence = int(sdo.get("confidence", 0))
        kill_chain = tuple(
            phase.get("phase_name", "")
            for phase in sdo.get("kill_chain_phases", [])
            if isinstance(phase, dict)
        )
        valid_from_ns = _to_ns(sdo.get("valid_from")) or 0
        valid_until_ns = _to_ns(sdo.get("valid_until"))

        out: list[Indicator] = []
        for ind_type, value in leaves:
            out.append(
                Indicator(
                    value=value,
                    type=ind_type,
                    source_feed=source_feed,
                    confidence=confidence,
                    kill_chain_phases=kill_chain,
                    valid_from_ns=valid_from_ns,
                    valid_until_ns=valid_until_ns,
                )
            )
        return tuple(out)


def _extract_leaves(node: Any) -> list[tuple[IndicatorType, str]]:
    """Walk a stix2 pattern AST and return (type, value) leaves."""
    leaves: list[tuple[IndicatorType, str]] = []
    _walk(node, leaves)
    return leaves


def _walk(node: Any, leaves: list[tuple[IndicatorType, str]]) -> None:
    # Composite boolean (AND / OR / FOLLOWEDBY) at the observation level.
    operands = getattr(node, "operands", None)
    if operands is not None:
        for child in operands:
            _walk(child, leaves)
        return

    # QualifiedObservationExpression wraps an inner observation expression.
    inner = getattr(node, "observation_expression", None)
    if inner is not None:
        _walk(inner, leaves)
        return

    # ObservationExpression -> single comparison expression operand.
    operand = getattr(node, "operand", None)
    if operand is not None:
        _walk_comparison(operand, leaves)
        return

    # Already a comparison expression at the top.
    if hasattr(node, "lhs") and hasattr(node, "rhs"):
        _walk_comparison(node, leaves)


def _walk_comparison(cmp: Any, leaves: list[tuple[IndicatorType, str]]) -> None:
    # AND / OR over comparisons
    operands = getattr(cmp, "operands", None)
    if operands is not None:
        for child in operands:
            _walk_comparison(child, leaves)
        return

    path = getattr(cmp, "lhs", None)
    rhs = getattr(cmp, "rhs", None)
    if path is None or rhs is None:
        return

    obj_type = (getattr(path, "object_type_name", "") or "").lower()
    prop_components = getattr(path, "property_path", None) or []
    prop_strs = tuple(
        str(getattr(p, "property_name", p)).lower().strip("'\"") for p in prop_components
    )

    value = getattr(rhs, "value", None)
    if value is None:
        return

    if obj_type == "file" and prop_strs and prop_strs[0] == "hashes":
        hash_kind = (prop_strs[1] if len(prop_strs) > 1 else "").strip("'\"").lower()
        mapped = _HASH_NAME_MAP.get(hash_kind)
        if mapped is not None:
            leaves.append((mapped, str(value)))
        return

    type_key: tuple[str, ...] = (obj_type, *prop_strs)
    mapped_t = _PATH_TYPE_MAP.get(type_key)
    if mapped_t is not None:
        leaves.append((mapped_t, str(value)))


def _to_ns(value: Any) -> int | None:
    if not value:
        return None
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        dt = value
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1_000_000_000)
