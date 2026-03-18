"""Entry point for ``python -m seerflow``."""

from seerflow import __version__


def main() -> None:
    """Print version and exit."""
    print(f"seerflow {__version__}")  # noqa: T201
    print("Not yet implemented. See: https://github.com/seerflow/seerflow")  # noqa: T201


if __name__ == "__main__":
    main()
