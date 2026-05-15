"""Convention guard: no redundant ``@pytest.mark.asyncio`` decorators.

``pyproject.toml`` sets ``asyncio_mode = "auto"`` for pytest-asyncio, so every
``async def`` test is collected automatically. An explicit
``@pytest.mark.asyncio`` (bare or call form) is therefore pure noise. This
meta-test scans the whole ``tests/`` tree and fails if any such decorator line
is present, keeping the convention enforced inside the regular test suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# A decorator line whose stripped content is exactly the asyncio marker, with
# or without empty parentheses. Anything else (e.g. a marker that takes real
# arguments) would not match — there is none in this project, by design.
_REDUNDANT_MARKER = re.compile(r"^@pytest\.mark\.asyncio(\(\))?$")

_TESTS_ROOT = Path(__file__).resolve().parent.parent
_THIS_FILE = Path(__file__).resolve()


def _offending_lines() -> list[str]:
    """Return ``path:lineno`` for every redundant asyncio-marker decorator."""
    offenders: list[str] = []
    for py_file in sorted(_TESTS_ROOT.rglob("*.py")):
        if py_file.resolve() == _THIS_FILE:
            # This file must reference the literal pattern in a regex/string.
            continue
        for lineno, raw in enumerate(py_file.read_text(encoding="utf-8").splitlines(), start=1):
            if _REDUNDANT_MARKER.match(raw.strip()):
                rel = py_file.relative_to(_TESTS_ROOT.parent)
                offenders.append(f"{rel}:{lineno}")
    return offenders


@pytest.mark.unit
def test_no_redundant_asyncio_markers() -> None:
    offenders = _offending_lines()
    assert not offenders, (
        f"{len(offenders)} redundant @pytest.mark.asyncio decorator(s) found. "
        "asyncio_mode='auto' collects async tests automatically — remove the "
        "decorator. Offenders:\n" + "\n".join(offenders)
    )
