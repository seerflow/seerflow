"""CLI surface + config threading for the console sink (S-312/FR-071)."""

from __future__ import annotations

import pytest

from seerflow.cli import parse_args
from seerflow.pipeline.tail import _build_tail_config


def test_start_accepts_alerts_flags() -> None:
    ns = parse_args(["start", "--alerts-to", "stderr", "--alerts-format", "json"])
    assert ns.alerts_to == "stderr"
    assert ns.alerts_format == "json"


def test_start_alerts_flags_default_none() -> None:
    ns = parse_args(["start"])
    assert ns.alerts_to is None
    assert ns.alerts_format is None


def test_start_alerts_to_accepts_non_stream_path() -> None:
    # S-312 and S-313 share ``--alerts-to``: a non-stdout/stderr value is a
    # valid file-sink path (no argparse ``choices`` rejection), routed to the
    # file sink by _apply_alerts_to rather than the console sink.
    ns = parse_args(["start", "--alerts-to", "/var/log/seerflow/alerts.ndjson"])
    assert ns.alerts_to == "/var/log/seerflow/alerts.ndjson"


def test_start_rejects_bad_format() -> None:
    with pytest.raises(SystemExit):
        parse_args(["start", "--alerts-format", "xml"])


def test_tail_config_enables_console_on_stdout() -> None:
    cfg = _build_tail_config(["/var/log/auth.log"])
    assert cfg.alerting.console_enabled is True
    assert cfg.alerting.console_stream == "stdout"


def test_tail_config_preserves_other_alerting_fields() -> None:
    cfg = _build_tail_config(["/var/log/auth.log"])
    # console fields forced on; format default preserved from base config.
    assert cfg.alerting.console_format == "human"
    assert tuple(cfg.receivers.file_paths) == ("/var/log/auth.log",)


def test_apply_console_overrides_noop_when_no_flags() -> None:
    from seerflow.__main__ import _apply_console_overrides
    from seerflow.config import SeerflowConfig

    cfg = SeerflowConfig()
    assert _apply_console_overrides(cfg, None, None) is cfg


def test_apply_console_overrides_sets_stream_and_format() -> None:
    from seerflow.__main__ import _apply_console_overrides
    from seerflow.config import SeerflowConfig

    cfg = SeerflowConfig()
    out = _apply_console_overrides(cfg, "stderr", "json")
    assert out.alerting.console_enabled is True
    assert out.alerting.console_stream == "stderr"
    assert out.alerting.console_format == "json"
    # frozen: original untouched (immutability).
    assert cfg.alerting.console_enabled is False


def test_apply_console_overrides_format_only_does_not_enable() -> None:
    from seerflow.__main__ import _apply_console_overrides
    from seerflow.config import SeerflowConfig

    cfg = SeerflowConfig()
    out = _apply_console_overrides(cfg, None, "json")
    assert out.alerting.console_format == "json"
    assert out.alerting.console_enabled is False
