"""S-238: enforce a single canonical DNS-guard bypass definition.

Mirrors ``tests/unit/test_asyncio_marker_convention.py``: a suite-level
guard so a future re-duplication of the per-file ``_bypass_dns_guard``
fixture (the S-227 defect this story closes) fails CI loudly instead of
silently re-introducing four identical fixture bodies.
"""

from __future__ import annotations

import re
from pathlib import Path

_TESTS_ROOT = Path(__file__).resolve().parent.parent
_DEF_RE = re.compile(
    r"^\s*def\s+(_bypass_dns_guard|apply_dns_guard_bypass)\b",
    re.MULTILINE,
)


def test_single_dns_guard_bypass_definition() -> None:
    hits: list[str] = []
    for path in _TESTS_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for _ in _DEF_RE.finditer(text):
            hits.append(str(path.relative_to(_TESTS_ROOT)))
    assert len(hits) == 1, (
        f"expected exactly one DNS-guard bypass definition, found: {sorted(hits)}"
    )
    assert hits[0] == "helpers.py", (
        f"canonical definition must live in tests/helpers.py, got {hits[0]}"
    )
