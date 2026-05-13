"""Regression guard — no production code imports the deleted aiohttp health module.

S-217 deleted ``seerflow.api.health``; the FastAPI ``/api/v1/health`` route
now mirrors its contract. This test fails if any module under ``src/``
re-introduces the legacy import.
"""

from __future__ import annotations

import pathlib
import re


class TestLegacyHealthRemoved:
    def test_no_module_imports_aiohttp_health(self) -> None:
        repo = pathlib.Path(__file__).resolve().parents[2]
        offenders: list[str] = []
        for py in (repo / "src").rglob("*.py"):
            text = py.read_text()
            if re.search(r"from\s+seerflow\.api\.health\s+import", text):
                offenders.append(str(py))
            if re.search(r"import\s+seerflow\.api\.health\b", text):
                offenders.append(str(py))
        assert not offenders, f"Legacy aiohttp health still imported: {offenders}"
