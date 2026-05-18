"""S-238: enforce a single canonical DNS-guard bypass definition.

Mirrors ``tests/unit/test_asyncio_marker_convention.py``: a suite-level
guard so a future re-duplication of the S-227 per-file ``_bypass_dns_guard``
fixture fails CI loudly instead of silently re-introducing identical
``monkeypatch.setattr(...)`` bodies.

The signal is the *bypass logic*, not the fixture name: thin autouse
conftests that merely *delegate* to ``tests.helpers.apply_dns_guard_bypass``
are not duplicate definitions. Re-duplication always re-introduces the
``monkeypatch.setattr(... _resolve_feed_with_private_ip_guard ...)`` call,
so that literal is the thing that must appear exactly once.
"""

from __future__ import annotations

from pathlib import Path

_SELF = Path(__file__).resolve()
_TESTS_ROOT = _SELF.parent.parent

# The exact monkeypatch target the bypass overrides. Any inline re-duplication
# of the old per-file fixture necessarily re-introduces this string.
_BYPASS_TARGET = '"seerflow.threat_intel.dns._resolve_feed_with_private_ip_guard"'


def test_single_dns_guard_bypass_definition() -> None:
    hits: list[str] = []
    for path in _TESTS_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if path.resolve() == _SELF:
            # This guard file names the target literal in _BYPASS_TARGET; it
            # is not a re-duplication of the bypass behaviour.
            continue
        if _BYPASS_TARGET in path.read_text(encoding="utf-8"):
            hits.append(str(path.relative_to(_TESTS_ROOT)))
    assert hits == ["helpers.py"], (
        "the DNS-guard bypass monkeypatch must exist exactly once, in "
        f"tests/helpers.py (apply_dns_guard_bypass); found in: {sorted(hits)}. "
        "Do not re-inline a per-file _bypass_dns_guard fixture — delegate to "
        "tests.helpers.apply_dns_guard_bypass via a directory conftest."
    )
