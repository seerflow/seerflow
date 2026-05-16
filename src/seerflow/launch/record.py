"""asciinema recording helper (S-090).

asciinema is an optional external tool -- never imported, only invoked via
``subprocess`` behind an explicit ``--exec``. Default behaviour just prints
the canonical command so the recording procedure is copy-pasteable offline.
"""

from __future__ import annotations

import argparse
import subprocess  # nosec B404 -- argv is a fixed list, no shell, --exec gated
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_DEFAULT_DEMO_CMD = "python -m seerflow.launch.demo"


def build_asciinema_command(cast_path: str, *, demo_cmd: str = _DEFAULT_DEMO_CMD) -> list[str]:
    """Return the canonical ``asciinema rec`` argv for the demo."""
    return [
        "asciinema",
        "rec",
        "--overwrite",
        "--command",
        demo_cmd,
        cast_path,
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    p = argparse.ArgumentParser(
        prog="seerflow.launch.record",
        description="Print (or run with --exec) the asciinema command "
        "that records the Seerflow demo.",
    )
    p.add_argument("cast_path", help="Output .cast file path")
    p.add_argument(
        "--demo-cmd",
        default=_DEFAULT_DEMO_CMD,
        help="Command asciinema wraps (default: the launch demo).",
    )
    p.add_argument(
        "--exec",
        action="store_true",
        help="Actually run asciinema (requires asciinema installed).",
    )
    ns = p.parse_args(sys.argv[1:] if argv is None else argv)
    cmd = build_asciinema_command(ns.cast_path, demo_cmd=ns.demo_cmd)
    if ns.exec:
        return subprocess.run(cmd, check=False).returncode  # noqa: S603  # nosec B603
    print(" ".join(cmd))  # noqa: T201 -- CLI stdout is the contract
    print(  # noqa: T201
        "\n# asciinema not run (no --exec). Install asciinema, then either\n"
        "# run the line above or re-run this with --exec."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
