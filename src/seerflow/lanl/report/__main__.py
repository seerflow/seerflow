"""Entry point for ``python -m seerflow.lanl.report``.

Delegates to the legacy Markdown renderer in
:mod:`seerflow.lanl.report_renderer` so existing usage is unchanged.
"""

from __future__ import annotations

import sys

from seerflow.lanl.report_renderer import _main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
