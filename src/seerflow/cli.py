"""CLI argument parsing for the seerflow command."""

from __future__ import annotations

import argparse

from seerflow import __version__


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="seerflow",
        description="Streaming log intelligence agent",
    )
    parser.add_argument(
        "--version", action="version", version=f"seerflow {__version__}"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to seerflow.yaml config file",
    )
    return parser.parse_args(argv)


__all__ = ["parse_args"]
