"""Structural guards for src/seerflow/config.py (S-172)."""

from __future__ import annotations

from pathlib import Path

import pytest

CONFIG_PATH = Path(__file__).resolve().parents[2] / "src" / "seerflow" / "config.py"


@pytest.mark.unit
def test_config_py_under_800_lines() -> None:
    """CLAUDE.md Code Quality Checklist: files <800 lines."""
    line_count = sum(1 for _ in CONFIG_PATH.open(encoding="utf-8"))
    assert line_count < 800, (
        f"src/seerflow/config.py is {line_count} lines; budget is <800. "
        "Extract validators/builders into _config_validation.py / _config_builders.py."
    )


@pytest.mark.unit
def test_public_api_importable() -> None:
    """All public names remain importable from seerflow.config."""
    from seerflow.config import (  # noqa: F401
        AlertingConfig,
        ConfigError,
        CorrelationConfig,
        DetectionConfig,
        GraphStructuralConfig,
        KillChainConfig,
        LLMConfig,
        ReceiverConfig,
        SeerflowConfig,
        StorageConfig,
        WebhookEndpointConfig,
        load_config,
    )


@pytest.mark.unit
def test_private_test_helpers_still_reexported() -> None:
    """tests/unit/test_config.py imports these names; they must survive the move."""
    from seerflow.config import (  # noqa: F401
        _build_alerting,
        _parse_ws_fields,
        _WsFields,
    )
