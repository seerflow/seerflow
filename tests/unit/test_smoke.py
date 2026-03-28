"""Smoke tests verifying the seerflow package structure is importable."""

from __future__ import annotations


def test_version_exists() -> None:
    import seerflow

    assert hasattr(seerflow, "__version__")
    assert isinstance(seerflow.__version__, str)
    parts = seerflow.__version__.split(".")
    assert len(parts) == 3, f"Expected semver X.Y.Z, got {seerflow.__version__}"
    assert all(p.isdigit() for p in parts), f"Non-numeric semver: {seerflow.__version__}"


def test_subpackages_importable() -> None:
    import seerflow.alerting
    import seerflow.api
    import seerflow.correlation
    import seerflow.detection
    import seerflow.llm
    import seerflow.models
    import seerflow.parsing
    import seerflow.receivers
    import seerflow.sigma
    import seerflow.storage
    import seerflow.threat_intel
    import seerflow.ueba
    import seerflow.utils

    # Verify all imports succeeded (no ImportError)
    assert seerflow.models is not None
    assert seerflow.receivers is not None
    assert seerflow.parsing is not None
    assert seerflow.detection is not None
    assert seerflow.sigma is not None
    assert seerflow.correlation is not None
    assert seerflow.ueba is not None
    assert seerflow.threat_intel is not None
    assert seerflow.storage is not None
    assert seerflow.alerting is not None
    assert seerflow.llm is not None
    assert seerflow.api is not None
    assert seerflow.utils is not None


def test_nested_subpackages_importable() -> None:
    import seerflow.alerting.sinks
    import seerflow.api.routes

    assert seerflow.alerting.sinks is not None
    assert seerflow.api.routes is not None


def test_main_entry_point() -> None:
    from seerflow.__main__ import main

    assert callable(main)


def test_cli_parse_args() -> None:
    from seerflow.cli import parse_args

    assert callable(parse_args)
    args = parse_args(["start"])
    assert args.command == "start"
    assert args.config is None
