"""FileSink is constructed + wired by the pipeline assembly (S-313/FR-072)."""

from __future__ import annotations

import dataclasses
import inspect
from typing import TYPE_CHECKING

from seerflow.config import AlertingConfig, SeerflowConfig
from seerflow.pipeline.assembly import _build_file_sink

if TYPE_CHECKING:
    from pathlib import Path


def test_file_sink_none_when_disabled() -> None:
    cfg = SeerflowConfig(alerting=AlertingConfig(file_enabled=False))
    sink, task = _build_file_sink(cfg)
    assert sink is None
    assert task is None


async def test_file_sink_built_when_enabled(tmp_path: Path) -> None:
    target = tmp_path / "alerts.ndjson"
    cfg = SeerflowConfig(
        alerting=AlertingConfig(
            file_enabled=True,
            file_path=str(target),
            file_rotation="time",
            file_min_severity=4,
        )
    )
    sink, task = _build_file_sink(cfg)
    try:
        assert sink is not None
        assert sink._path == str(target)
        assert sink._min_severity == 4
        assert task is not None
    finally:
        if sink is not None:
            await sink.stop()
        if task is not None:
            await task
        if sink is not None:
            await sink.close()


def test_handler_accepts_file_sink_param() -> None:
    from seerflow.pipeline.handler import make_handler

    sig = inspect.signature(make_handler)
    assert "file_sink" in sig.parameters


async def test_build_alert_sinks_returns_file_sink_slot(tmp_path: Path) -> None:
    from seerflow.pipeline.assembly import _build_alert_sinks

    target = tmp_path / "a.ndjson"
    base = SeerflowConfig()
    cfg = dataclasses.replace(
        base,
        alerting=dataclasses.replace(base.alerting, file_enabled=True, file_path=str(target)),
    )
    result = await _build_alert_sinks(cfg)
    assert len(result) == 10
    file_sink, file_task = result[8], result[9]
    try:
        assert file_sink is not None
    finally:
        if file_sink is not None:
            await file_sink.stop()
        if file_task is not None:
            await file_task
        if file_sink is not None:
            await file_sink.close()
        # drain the other constructed sinks/sessions
        webhook_session = result[0]
        if webhook_session is not None:
            await webhook_session.close()
