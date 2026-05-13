#!/usr/bin/env python3
"""Abort wheel builds missing the dashboard when gated (S-057).

Opt-in via ``SEERFLOW_REQUIRE_FRONTEND=1``. Designed to be invoked
before ``uv build`` in release workflows so a dashboard-less wheel
never ships to PyPI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_INDEX = Path(__file__).resolve().parent / "src" / "seerflow" / "web" / "dist" / "index.html"


def main() -> int:
    if os.environ.get("SEERFLOW_REQUIRE_FRONTEND", "0") != "1":
        return 0
    if _INDEX.is_file():
        return 0
    sys.stderr.write(
        f"frontend build missing: expected {_INDEX}\n"
        "Run `./build_frontend.sh` or "
        "`npm ci --prefix frontend && npm run build --prefix frontend`\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
