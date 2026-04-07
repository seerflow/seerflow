"""MITRE ATT&CK mapping for ML anomaly alert templates.

Maps Drain3 template strings to ATT&CK tactics and techniques via
configurable regex patterns.  Patterns are matched case-insensitively;
first match wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_EMPTY: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AttackMapping:
    """Single regex-to-ATT&CK mapping entry."""

    pattern: re.Pattern[str]
    tactics: tuple[str, ...]
    techniques: tuple[str, ...]

    @classmethod
    def from_raw(
        cls,
        *,
        pattern: str,
        tactics: list[str],
        techniques: list[str],
    ) -> AttackMapping:
        """Compile *pattern* (case-insensitive) and wrap in a mapping."""
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            msg = f"Invalid regex in attack mapping: {pattern!r} — {exc}"
            raise ValueError(msg) from exc
        return cls(
            pattern=compiled,
            tactics=tuple(tactics),
            techniques=tuple(techniques),
        )


class AttackMapper:
    """Look up ATT&CK tactics/techniques for a log template string.

    Iterates over mappings in order; first match wins.
    """

    __slots__ = ("_mappings",)

    def __init__(self, mappings: list[AttackMapping]) -> None:
        self._mappings = mappings

    def lookup(self, template: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return ``(tactics, techniques)`` for *template*, or empty tuples."""
        for mapping in self._mappings:
            if mapping.pattern.search(template):
                return mapping.tactics, mapping.techniques
        return _EMPTY, _EMPTY

    @classmethod
    def from_config(cls, raw: list[dict[str, Any]]) -> AttackMapper:
        """Build a mapper from a list of raw config dicts."""
        mappings = [
            AttackMapping.from_raw(
                pattern=entry["pattern"],
                tactics=entry.get("tactics", []),
                techniques=entry.get("techniques", []),
            )
            for entry in raw
        ]
        return cls(mappings)

    def __len__(self) -> int:
        return len(self._mappings)
