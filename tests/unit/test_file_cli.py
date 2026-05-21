"""`seerflow start --alerts-to <path>` parsing + frozen-config override (S-313)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.__main__ import _apply_alerts_to
from seerflow.cli import parse_args
from seerflow.config import SeerflowConfig

if TYPE_CHECKING:
    from pathlib import Path


def test_start_accepts_alerts_to_path() -> None:
    ns = parse_args(["start", "--alerts-to", "/tmp/a.ndjson"])
    assert ns.command == "start"
    assert ns.alerts_to == "/tmp/a.ndjson"


def test_start_alerts_to_defaults_none() -> None:
    ns = parse_args(["start"])
    assert ns.alerts_to is None


def test_apply_alerts_to_sets_file_target(tmp_path: Path) -> None:
    target = tmp_path / "cli.ndjson"
    cfg = _apply_alerts_to(SeerflowConfig(), str(target))
    assert cfg.alerting.file_enabled is True
    assert cfg.alerting.file_path == str(target)


def test_apply_alerts_to_none_is_identity() -> None:
    base = SeerflowConfig()
    assert _apply_alerts_to(base, None) is base


def test_apply_alerts_to_preserves_other_alerting_fields(tmp_path: Path) -> None:
    base = SeerflowConfig()
    cfg = _apply_alerts_to(base, str(tmp_path / "c.ndjson"))
    assert cfg.alerting.dedup_window_seconds == base.alerting.dedup_window_seconds
    assert cfg.alerting.otlp_endpoint == base.alerting.otlp_endpoint
