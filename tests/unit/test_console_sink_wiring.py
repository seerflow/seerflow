"""ConsoleSink is constructed by _build_console_sink only when enabled (S-312)."""

from __future__ import annotations

from seerflow.config import AlertingConfig, SeerflowConfig
from seerflow.pipeline.assembly import _build_console_sink


async def test_console_sink_none_when_disabled() -> None:
    cfg = SeerflowConfig(alerting=AlertingConfig(console_enabled=False))
    sink, task = _build_console_sink(cfg)
    assert sink is None
    assert task is None


async def test_console_sink_built_when_enabled() -> None:
    import sys

    cfg = SeerflowConfig(
        alerting=AlertingConfig(
            console_enabled=True, console_stream="stderr", console_format="json"
        )
    )
    sink, task = _build_console_sink(cfg)
    try:
        assert sink is not None
        assert sink._stream is sys.stderr
        assert sink._fmt == "json"
        assert task is not None
    finally:
        if task is not None:
            task.cancel()


async def test_console_sink_passes_min_severity() -> None:
    cfg = SeerflowConfig(alerting=AlertingConfig(console_enabled=True, console_min_severity=4))
    sink, task = _build_console_sink(cfg)
    try:
        assert sink is not None
        assert sink._min_severity == 4
    finally:
        if task is not None:
            task.cancel()


def test_handler_accepts_console_sink_param() -> None:
    import inspect

    from seerflow.pipeline.handler import make_handler

    sig = inspect.signature(make_handler)
    assert "console_sink" in sig.parameters
    assert sig.parameters["console_sink"].default is None
